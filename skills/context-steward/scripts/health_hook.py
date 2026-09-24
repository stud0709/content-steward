#!/usr/bin/env python3
"""
Antigravity PreInvocation Context Health Hook
=============================================
Executed by Antigravity runtime prior to model invocations.
Transition-Boundary Aware Context Health Guard:
- Monitors conversation token count and depth.
- Silent on LEAN contexts (<40k tokens & <20 turns).
- On HEAVY (>60k-80k tokens) or MODERATE (turns >= 25):
  * Transition Boundary (Artifact written: implementation_plan.md or walkthrough.md):
    Injects transition boundary advisory with embedded Lossless Handoff prompt.
  * Execution Approval Boundary (user says 'proceed', 'go ahead', etc. with existing plan):
    Injects execution boundary warning advising subagent delegation or fresh conversation.
  * Non-Boundary / In-Progress Q&A:
    If HEAVY: Injects quiet context telemetry warning the model NOT to nag or emit handoffs.
    If MODERATE: Silent.
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


def is_execution_command(text: str) -> bool:
    """Checks if the user's input is an execution approval / launch command."""
    if not text:
        return False

    # Remove XML / markdown tags like <USER_REQUEST>, <ADDITIONAL_METADATA>, etc.
    clean = re.sub(r"<[^>]+>", " ", text)
    clean = clean.strip()
    if not clean:
        return False

    # If the user is asking a question, it's not an execution command
    if clean.endswith("?"):
        return False

    first_few = clean.lower()[:30]
    if re.search(r"\b(is|are|why|how|what|where|when|who|which|can|could|should|would)\b", first_few):
        return False

    # Normalize: remove apostrophes and punctuation, lowercase
    clean_no_apos = clean.replace("'", "").replace("’", "")
    norm = re.sub(r"[^\w\s]", " ", clean_no_apos).strip().lower()
    norm = " ".join(norm.split())

    exact_commands = {
        "proceed", "go ahead", "implement", "start", "approved", "approve",
        "yes", "do it", "lets go", "run it", "execute", "lgtm",
        "looks good", "go for it", "please proceed", "continue", "make it so",
        "sounds good proceed", "looks good proceed", "yes please", "yes proceed",
        "ready to proceed", "confirmed", "confirm"
    }
    if norm in exact_commands:
        return True

    words = norm.split()
    if len(words) <= 10:
        first_word = words[0] if words else ""
        first_two = " ".join(words[:2]) if len(words) >= 2 else ""
        if first_word in {"proceed", "implement", "start", "execute"} or first_two in {
            "go ahead", "do it", "lets go", "please proceed", "run it"
        }:
            return True

    return False


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

        # Silent on LEAN or small conversations
        if status == "LEAN" or (current_context < 40000 and total_turns < 20):
            print("{}")
            return

        # Only evaluate boundaries if HEAVY or MODERATE with total_turns >= 25
        if status != "HEAVY" and not (status == "MODERATE" and total_turns >= 25):
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
        latest_user_text = extract_user_request_text(latest_user_step.get("content", "")) if latest_user_step else ""
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

        # Check B: Execution Approval Boundary
        plan_exists = False
        if artifact_dir and (artifact_dir / "implementation_plan.md").exists():
            plan_exists = True

        if plan_exists and is_execution_command(latest_user_text):
            target_art_path = (artifact_dir / "implementation_plan.md") if artifact_dir else None
            handoff_text, artifact = count_tokens.generate_handoff_prompt(
                conv_id, title or "(Untitled)", search_dirs, target_artifact=target_art_path
            )
            status_str = "🔴 HEAVY" if status == "HEAVY" else "🟡 MODERATE"
            msg = (
                f"[EXECUTION BOUNDARY IN {status_str} CONTEXT ({current_context:,} tokens)]\n"
                f"The user requested execution, but this conversation is {status_str} ({current_context:,} tokens).\n"
                f"Per Universal Context Hygiene (§ 1, § 5, & § 6):\n"
                f"1. Recommend launching a fresh thread using the Lossless Handoff prompt below, OR\n"
                f"2. If continuing in this thread, you MUST NOT execute code edits or run test loops directly in the parent context. You MUST package the scope into an Execution Packet and immediately delegate to a worker subagent.\n\n"
                f"--------------------------------------------------------------------------\n"
                f"{handoff_text}\n"
                f"--------------------------------------------------------------------------"
            )
            output = {"injectSteps": [{"ephemeralMessage": msg}]}
            print(json.dumps(output))
            return

        # Check C: Non-Boundary / In-Progress Q&A
        if status == "HEAVY":
            msg = (
                f"[Context Telemetry: 🔴 HEAVY ({current_context:,} tokens in context)]\n"
                f"Active in-progress turn. Answer the user's inquiry concisely.\n"
                f"NOTE: Do NOT nag the user and do NOT append handoff prompts during normal conversational Q&A. Reserve handoffs strictly for plan/milestone boundaries."
            )
            output = {"injectSteps": [{"ephemeralMessage": msg}]}
            print(json.dumps(output))
            return

        # If MODERATE and not at a boundary: silent
        print("{}")
    except Exception:
        # Failsafe: never break the agent invocation
        print("{}")


if __name__ == "__main__":
    main()
