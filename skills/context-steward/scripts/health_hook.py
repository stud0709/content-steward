#!/usr/bin/env python3
"""
Antigravity PreInvocation Context Health Hook
=============================================
Executed by Antigravity runtime prior to model invocations.
Transition-Boundary Aware Context Health Guard:
- Monitors conversation token count and depth.
- Silent on LEAN contexts (<40k tokens & <20 turns).
- If MODERATE (<25 turns) and no artifact written: silent.
- On HEAVY or MODERATE:
  * Transition Boundary (Artifact written: implementation_plan.md or walkthrough.md):
    Injects transition boundary advisory with embedded Lossless Handoff prompt.
- On HEAVY:
  * Active Plan Telemetry (implementation_plan.md exists in brain directory):
    Injects telemetry advising the model: if user approves execution, delegate or fresh thread;
    if user clarifies/inquires, answer concisely without nagging.
  * General In-Progress Telemetry (no active plan):
    Injects quiet context telemetry warning the model to answer concisely and not nag.
"""

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ensure UTF-8 input/output on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def extract_user_request_text(content: str) -> str:
    """Extracts raw text from a USER_INPUT step content."""
    if not content:
        return ""
    m = re.search(r"<USER_REQUEST>(.*?)</USER_REQUEST>", content, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return content.strip()


def parse_step_timestamp(step: Dict[str, Any]) -> Optional[float]:
    """Parses created_at timestamp string into seconds epoch."""
    ts_str = step.get("created_at")
    if not ts_str:
        return None
    try:
        ts = ts_str.replace("Z", "+00:00")
        return datetime.fromisoformat(ts).timestamp()
    except Exception:
        return None


def slice_transcript_steps(all_steps: List[Dict[str, Any]], payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Slices transcript steps according to stepIdx, step_index, or initialNumSteps."""
    target = (
        payload.get("stepIdx")
        or payload.get("step_index")
        or payload.get("targetStep")
        or payload.get("target_step")
    )
    if target is not None:
        try:
            target_num = int(target)
            matching = [i for i, s in enumerate(all_steps) if s.get("step_index") == target_num]
            if matching:
                return all_steps[:matching[0] + 1]
            if 0 <= target_num < len(all_steps):
                return all_steps[:target_num + 1]
        except (ValueError, TypeError):
            pass

    initial_num_steps = payload.get("initialNumSteps")
    if isinstance(initial_num_steps, int) and 0 < initial_num_steps <= len(all_steps):
        return all_steps[:initial_num_steps]

    return all_steps


def detect_written_artifact(
    steps: List[Dict[str, Any]],
    artifact_dir: Optional[Path],
    latest_user_time: Optional[float] = None
) -> Optional[str]:
    """
    Checks if implementation_plan.md or walkthrough.md was written in recent steps
    of the current turn, or has mtime < 120 seconds ago.
    Returns the artifact filename if detected, else None.
    """
    target_artifacts = ("implementation_plan.md", "walkthrough.md")

    # 1. Inspect recent steps (last 10 steps or steps in current turn)
    user_indices = [i for i, s in enumerate(steps) if s.get("type") == "USER_INPUT"]
    start_idx = user_indices[-1] if user_indices else max(0, len(steps) - 10)
    # Also inspect at least the last 10 steps even if user input was earlier
    start_idx = min(start_idx, max(0, len(steps) - 10))

    for s in reversed(steps[start_idx:]):
        tool_calls = s.get("tool_calls", [])
        if not isinstance(tool_calls, list):
            continue
        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            name = call.get("name") or call.get("tool_name")
            if name == "write_to_file":
                args = call.get("args", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                target_file = str(args.get("TargetFile", "")).strip('\"\'').replace("\\", "/").lower()
                for art in target_artifacts:
                    if target_file.endswith("/" + art) or target_file == art:
                        return art

    # 2. Check artifact directory modification times (< 120 seconds ago)
    if artifact_dir and artifact_dir.exists():
        now = time.time()
        for art in target_artifacts:
            fpath = artifact_dir / art
            if fpath.exists():
                try:
                    mtime = fpath.stat().st_mtime
                    age = now - mtime
                    if 0 <= age < 120:
                        if latest_user_time is None or mtime >= (latest_user_time - 5):
                            return art
                except Exception:
                    pass

    return None


def check_plan_exists(
    steps: List[Dict[str, Any]],
    artifact_dir: Optional[Path],
    is_sliced: bool = False
) -> bool:
    """
    Checks if an implementation_plan.md is currently active for the conversation.
    A plan is active if implementation_plan.md exists and has not been superseded
    by a subsequent walkthrough.md completing the milestone.
    """
    if not artifact_dir:
        return False

    plan_file = artifact_dir / "implementation_plan.md"
    if not plan_file.exists():
        return False

    # 1. If steps are available from transcript (sliced or unsliced), check step order
    if steps:
        last_plan_step = None
        last_walk_step = None
        for s in steps:
            tool_calls = s.get("tool_calls", [])
            if not isinstance(tool_calls, list):
                continue
            for call in tool_calls:
                if not isinstance(call, dict):
                    continue
                name = call.get("name") or call.get("tool_name")
                if name == "write_to_file":
                    args = call.get("args", {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            args = {}
                    target_file = str(args.get("TargetFile", "")).strip('\"\'').replace("\\", "/").lower()
                    if target_file.endswith("/implementation_plan.md") or target_file == "implementation_plan.md":
                        last_plan_step = s.get("step_index")
                    elif target_file.endswith("/walkthrough.md") or target_file == "walkthrough.md":
                        last_walk_step = s.get("step_index")

        if last_plan_step is not None:
            if last_walk_step is not None and last_walk_step > last_plan_step:
                # Walkthrough was written after the plan, so the plan is already completed
                return False
            return True

        if is_sliced:
            # Plan was not authored in the sliced steps; check if file mtime was before the sliced step
            last_step_time = parse_step_timestamp(steps[-1])
            if last_step_time is not None:
                try:
                    mtime = plan_file.stat().st_mtime
                    if mtime > (last_step_time + 10):
                        return False
                except Exception:
                    pass

    # 2. Filesystem mtime check: if walkthrough is newer than plan, plan is completed
    walk_file = artifact_dir / "walkthrough.md"
    if walk_file.exists():
        try:
            if walk_file.stat().st_mtime > plan_file.stat().st_mtime:
                return False
        except Exception:
            pass

    return True


def main():
    try:
        raw_input = sys.stdin.read()
        if not raw_input:
            print("{}")
            return

        raw_input = raw_input.lstrip("\ufeff").lstrip("ï»¿").strip()
        if not raw_input:
            print("{}")
            return

        payload = json.loads(raw_input)
    except Exception:
        print("{}")
        return

    conv_id = payload.get("conversationId")
    if not conv_id:
        print("{}")
        return

    # Add parent directory to sys.path to import count_tokens
    script_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(script_dir))

    try:
        import count_tokens
        search_dirs = count_tokens.get_search_directories()
        db_path, title = count_tokens.find_conversation_db(conv_id, search_dirs)
        if not db_path or not db_path.exists():
            print("{}")
            return

        stats = count_tokens.analyze_conversation_tokens(db_path, search_dirs)
        health = stats.get("health", {})
        status = health.get("status", "LEAN")
        current_context = stats.get("current_context_tokens", 0)
        total_turns = stats.get("total_turns", 0)

        # Silent on LEAN or small conversations (<40k tokens & <20 turns)
        if status == "LEAN" or (current_context < 40000 and total_turns < 20):
            print("{}")
            return

        # Resolve artifact directory path
        artifact_dir = None
        if payload.get("artifactDirectoryPath"):
            candidate = Path(payload["artifactDirectoryPath"])
            if candidate.exists():
                artifact_dir = candidate

        if not artifact_dir:
            for b in search_dirs:
                candidate = b / "brain" / conv_id
                if candidate.exists():
                    artifact_dir = candidate
                    break

        # Resolve transcript path
        transcript_path = None
        if payload.get("transcriptPath"):
            candidate = Path(payload["transcriptPath"])
            if candidate.exists():
                transcript_path = candidate

        if not transcript_path and artifact_dir:
            candidate = artifact_dir / ".system_generated" / "logs" / "transcript.jsonl"
            if candidate.exists():
                transcript_path = candidate

        # Load and slice transcript steps
        steps = []
        is_sliced = bool(
            payload.get("stepIdx")
            or payload.get("step_index")
            or payload.get("targetStep")
            or payload.get("target_step")
            or payload.get("initialNumSteps")
        )
        if transcript_path and transcript_path.exists():
            try:
                raw_lines = transcript_path.read_text(encoding="utf-8", errors="ignore").strip().split("\n")
                all_steps = [json.loads(line) for line in raw_lines if line.strip()]
                steps = slice_transcript_steps(all_steps, payload)
            except Exception:
                steps = []

        # Find latest USER_INPUT and its timestamp
        user_steps = [s for s in steps if s.get("type") == "USER_INPUT"]
        latest_user_step = user_steps[-1] if user_steps else None
        latest_user_time = parse_step_timestamp(latest_user_step) if latest_user_step else None

        # Check A: Transition Boundary (Artifact Written)
        detected_art = detect_written_artifact(steps, artifact_dir, latest_user_time)
        if detected_art:
            target_art_path = (artifact_dir / detected_art) if artifact_dir else None
            handoff_text, artifact = count_tokens.generate_handoff_prompt(
                conv_id, title or "(Untitled)", search_dirs, target_artifact=target_art_path
            )
            art_display = artifact.name if artifact else detected_art
            badge_str = "🔴 HEAVY CONTEXT" if status == "HEAVY" else "🟡 MODERATE CONTEXT"
            msg = (
                f"[TRANSITION BOUNDARY: {badge_str} ({current_context:,} tokens, {total_turns} turns)]\n"
                f"An artifact ({art_display}) was just authored.\n"
                f"Per Universal Context Hygiene Rules (§ 1 & § 5):\n"
                f"- Do NOT invite the user to execute directly in this thread.\n"
                f"- Present your plan/milestone summary and append this ready-to-copy Lossless Handoff block verbatim:\n\n"
                f"--------------------------------------------------------------------------\n"
                f"{handoff_text}\n"
                f"--------------------------------------------------------------------------\n\n"
                f"Advise the user to paste this block into a fresh conversation so execution and verification begin in a lean 🟢 LEAN context."
            )
            output = {"injectSteps": [{"ephemeralMessage": msg}]}
            print(json.dumps(output))
            return

        # If MODERATE and no artifact written: return {} (silent)
        if status != "HEAVY":
            print("{}")
            return

        # Check B: Active Plan Telemetry (implementation_plan.md exists and status == HEAVY)
        if check_plan_exists(steps, artifact_dir, is_sliced):
            msg = (
                f"[Context Telemetry: 🔴 HEAVY ({current_context:,} tokens) | Active Plan]\n"
                f"- If the user is approving, confirming, or requesting implementation (e.g. \"sounds good\", \"proceed\", \"go ahead\", \"let's do it\"):\n"
                f"  Per Universal Rules § 5 & § 6, do NOT execute code edits directly in this main thread. Either reiterate the Lossless Handoff prompt to run in a fresh lean thread, or delegate immediately to a worker subagent with an Execution Packet.\n"
                f"- If the user is asking an inquiry or clarifying:\n"
                f"  Answer concisely. Do NOT nag the user and do NOT append handoff prompts during normal conversational Q&A."
            )
            output = {"injectSteps": [{"ephemeralMessage": msg}]}
            print(json.dumps(output))
            return

        # Check C: General In-Progress Telemetry (status == HEAVY, no plan active)
        msg = (
            f"[Context Telemetry: 🔴 HEAVY ({current_context:,} tokens in context)]\n"
            f"Active in-progress turn. Answer the user's inquiry concisely.\n"
            f"NOTE: Do NOT nag the user and do NOT append handoff prompts during normal conversational Q&A. Reserve handoffs strictly for plan/milestone boundaries."
        )
        output = {"injectSteps": [{"ephemeralMessage": msg}]}
        print(json.dumps(output))
    except Exception:
        # Failsafe: never break the agent invocation
        print("{}")


if __name__ == "__main__":
    main()
