#!/usr/bin/env python3
"""
Test Suite for Transition-Boundary-Aware Context Health Hook
============================================================
Tests:
- Unit parsing and helper functions (step slicing, artifact detection, plan checking)
- Payload parsing and BOM handling
- Real conversation 82061474-e281-4a81-a2eb-73c9a7af8842:
  * test_lean_conversation_silent: LEAN context returns {}
  * test_heavy_conversation_qa_mode: Step 550 Q&A inquiry -> quiet telemetry mode (no handoff prompt, no active plan)
  * test_heavy_conversation_artifact_boundary: Step 558 transition boundary after write_to_file implementation_plan.md
  * test_heavy_conversation_active_plan_telemetry: user turn when plan exists -> active plan telemetry guidance
- Direct end-of-transcript pipe invocation
- Compliance with Antigravity PreInvocation schema: {"injectSteps": [{"ephemeralMessage": ...}]} or {}
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

# Add scripts directory to sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "skills" / "context-steward" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import health_hook
import count_tokens

REAL_CONV_ID = "82061474-e281-4a81-a2eb-73c9a7af8842"


class TestHealthHookUnit(unittest.TestCase):
    """Unit tests for individual helper functions in health_hook.py."""

    def test_extract_user_request_text(self):
        xml_content = "<USER_REQUEST>\nhello world\n</USER_REQUEST>\n<ADDITIONAL_METADATA>\ninfo\n</ADDITIONAL_METADATA>"
        self.assertEqual(health_hook.extract_user_request_text(xml_content), "hello world")
        self.assertEqual(health_hook.extract_user_request_text("plain request"), "plain request")
        self.assertEqual(health_hook.extract_user_request_text(""), "")

    def test_detect_written_artifact(self):
        # Steps with write_to_file on implementation_plan.md
        steps_plan = [
            {"step_index": 1, "type": "USER_INPUT", "content": "make a plan"},
            {
                "step_index": 2,
                "type": "PLANNER_RESPONSE",
                "tool_calls": [
                    {
                        "name": "write_to_file",
                        "args": {
                            "TargetFile": "C:\\path\\to\\implementation_plan.md"
                        },
                    }
                ],
            },
            {"step_index": 3, "type": "GENERIC", "content": "File created"},
        ]
        self.assertEqual(
            health_hook.detect_written_artifact(steps_plan, None),
            "implementation_plan.md",
        )

        # Steps with write_to_file on walkthrough.md
        steps_walkthrough = [
            {"step_index": 1, "type": "USER_INPUT", "content": "update walkthrough"},
            {
                "step_index": 2,
                "type": "PLANNER_RESPONSE",
                "tool_calls": [
                    {
                        "name": "write_to_file",
                        "args": {
                            "TargetFile": "\"/some/dir/walkthrough.md\""
                        },
                    }
                ],
            },
        ]
        self.assertEqual(
            health_hook.detect_written_artifact(steps_walkthrough, None),
            "walkthrough.md",
        )

        # Steps without artifact writes
        steps_no_artifact = [
            {"step_index": 1, "type": "USER_INPUT", "content": "hello"},
            {
                "step_index": 2,
                "type": "PLANNER_RESPONSE",
                "tool_calls": [
                    {
                        "name": "run_command",
                        "args": {"CommandLine": "npm test"},
                    }
                ],
            },
        ]
        self.assertIsNone(health_hook.detect_written_artifact(steps_no_artifact, None))

    def test_check_plan_exists(self):
        # When artifact_dir is None
        self.assertFalse(health_hook.check_plan_exists([], None))

        # When artifact_dir has implementation_plan.md and not sliced
        brain_dir = Path("C:/Users/YuriyDzhenyeyev/.gemini/antigravity/brain") / REAL_CONV_ID
        if (brain_dir / "implementation_plan.md").exists():
            self.assertTrue(health_hook.check_plan_exists([], brain_dir, is_sliced=False))

    def test_slice_transcript_steps(self):
        steps = [
            {"step_index": 10, "type": "USER_INPUT"},
            {"step_index": 20, "type": "PLANNER_RESPONSE"},
            {"step_index": 30, "type": "PLANNER_RESPONSE"},
        ]
        # Target stepIdx 20
        sliced = health_hook.slice_transcript_steps(steps, {"stepIdx": 20})
        self.assertEqual(len(sliced), 2)
        self.assertEqual(sliced[-1]["step_index"], 20)

        # None -> all steps
        self.assertEqual(len(health_hook.slice_transcript_steps(steps, {})), 3)


class TestHealthHookSubprocess(unittest.TestCase):
    """Subprocess tests simulating native Antigravity PreInvocation hook invocations."""

    def _run_hook(self, payload_dict: dict) -> dict:
        """Executes health_hook.py via subprocess and returns parsed stdout JSON."""
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "health_hook.py")],
            input=json.dumps(payload_dict),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, f"Hook failed with stderr: {proc.stderr}")
        try:
            return json.loads(proc.stdout.strip())
        except json.JSONDecodeError as err:
            self.fail(f"Hook stdout is not valid JSON: {proc.stdout!r} ({err})")

    def test_payload_parsing_and_bom(self):
        """Tests payload parsing, UTF-8 BOM prefix handling, empty input, and malformed JSON."""
        # 1. Valid payload with UTF-8 BOM
        proc_bom = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "health_hook.py")],
            input="\ufeff" + json.dumps({"conversationId": REAL_CONV_ID, "stepIdx": 550}),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(proc_bom.returncode, 0)
        out_bom = json.loads(proc_bom.stdout.strip())
        self.assertIn("injectSteps", out_bom)

        # 2. Empty input
        proc_empty = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "health_hook.py")],
            input="",
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(proc_empty.returncode, 0)
        self.assertEqual(json.loads(proc_empty.stdout.strip()), {})

        # 3. Malformed JSON
        proc_invalid = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "health_hook.py")],
            input="{not valid json",
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(proc_invalid.returncode, 0)
        self.assertEqual(json.loads(proc_invalid.stdout.strip()), {})

        # 4. Unknown conversation ID
        out_unknown = self._run_hook({"conversationId": "00000000-0000-0000-0000-000000000000"})
        self.assertEqual(out_unknown, {})

    def test_lean_conversation_silent(self):
        """Tests that a LEAN conversation returns empty JSON {}."""
        search_dirs = count_tokens.get_search_directories()
        recent = count_tokens.list_conversations(search_dirs, limit=30)
        lean_id = None
        for r in recent:
            stats = count_tokens.analyze_conversation_tokens(Path(r["db_path"]), search_dirs)
            if stats.get("health", {}).get("status") == "LEAN":
                lean_id = r["id"]
                break
        if not lean_id:
            lean_id = "38d3c86d-3f17-4259-8a52-d1b6f239ee2e"

        out = self._run_hook({"conversationId": lean_id})
        self.assertEqual(out, {})

    def test_heavy_conversation_qa_mode(self):
        """
        Step 550 of 82061474 is an in-progress Q&A inquiry:
        User asks: 'are "banned / blocked / rate-limited" standard values...'
        Expects:
        - Output is valid PreInvocation JSON.
        - injectSteps contains quiet telemetry advisory.
        - Mentions '🔴 HEAVY' and 'Do NOT nag the user'.
        - Does NOT contain handoff prompt ('Please implement...').
        - Does NOT contain '| Active Plan'.
        """
        out = self._run_hook({"conversationId": REAL_CONV_ID, "stepIdx": 550})
        self.assertIn("injectSteps", out)
        steps = out["injectSteps"]
        self.assertEqual(len(steps), 1)
        msg = steps[0].get("ephemeralMessage", "")
        self.assertIn("[Context Telemetry: 🔴 HEAVY", msg)
        self.assertIn("Active in-progress turn", msg)
        self.assertIn("Do NOT nag the user", msg)
        self.assertNotIn("Please implement", msg)
        self.assertNotIn("Lossless Handoff", msg)
        self.assertNotIn("| Active Plan", msg)

    def test_heavy_conversation_artifact_boundary(self):
        """
        Step 558 of 82061474 occurs immediately after step 556 authored implementation_plan.md.
        Expects:
        - Output is valid PreInvocation JSON.
        - injectSteps contains transition boundary alert.
        - Contains 'implementation_plan.md was just authored'.
        - Contains ready-to-copy Lossless Handoff block with file targets and parent conversation link.
        """
        out = self._run_hook({"conversationId": REAL_CONV_ID, "stepIdx": 558})
        self.assertIn("injectSteps", out)
        steps = out["injectSteps"]
        self.assertEqual(len(steps), 1)
        msg = steps[0].get("ephemeralMessage", "")
        self.assertIn("[TRANSITION BOUNDARY: 🔴 HEAVY CONTEXT", msg)
        self.assertIn("implementation_plan.md", msg)
        self.assertIn("Please implement NIP-20 Prefix-Aware Reactive Backoff & Circuit Breaker according to @[file:", msg)
        self.assertIn("sap-bridge/tunnel/nostr.go", msg)
        self.assertIn('Reference parent conversation: @[conversation:"Bridge Handover Bug Analysis"].', msg)
        self.assertIn("Advise the user to paste this block into a fresh conversation", msg)

    def test_heavy_conversation_active_plan_telemetry(self):
        """
        When implementation_plan.md exists in the brain directory and conversation is HEAVY,
        but current step is a regular user turn (no artifact was authored in this turn).
        Expects:
        - Output is valid PreInvocation JSON.
        - injectSteps contains Active Plan telemetry.
        - Contains '[Context Telemetry: 🔴 HEAVY (...) | Active Plan]'.
        - Instructs model: if user approves execution, delegate or fresh thread;
          if user clarifies/inquires, answer concisely without nagging.
        """
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8") as tf:
            tf.write(json.dumps({
                "step_index": 1,
                "source": "USER_EXPLICIT",
                "type": "USER_INPUT",
                "content": "<USER_REQUEST>\nsounds good, please proceed\n</USER_REQUEST>"
            }) + "\n")
            temp_path = tf.name

        try:
            brain_dir = Path("C:/Users/YuriyDzhenyeyev/.gemini/antigravity/brain") / REAL_CONV_ID
            payload = {
                "conversationId": REAL_CONV_ID,
                "transcriptPath": temp_path,
                "artifactDirectoryPath": str(brain_dir),
            }
            out = self._run_hook(payload)
            self.assertIn("injectSteps", out)
            steps = out["injectSteps"]
            self.assertEqual(len(steps), 1)
            msg = steps[0].get("ephemeralMessage", "")
            self.assertIn("[Context Telemetry: 🔴 HEAVY", msg)
            self.assertIn("| Active Plan", msg)
            self.assertIn("If the user is approving, confirming, or requesting implementation", msg)
            self.assertIn("Per Universal Rules § 5 & § 6, do NOT execute code edits directly in this main thread", msg)
            self.assertIn("If the user is asking an inquiry or clarifying", msg)
            self.assertIn("Do NOT nag the user", msg)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_real_conversation_direct_invocation(self):
        """Tests health_hook.py without stepIdx (evaluates end of transcript)."""
        out = self._run_hook({"conversationId": REAL_CONV_ID})
        self.assertIn("injectSteps", out)
        steps = out["injectSteps"]
        self.assertEqual(len(steps), 1)
        msg = steps[0].get("ephemeralMessage", "")
        self.assertIn("[TRANSITION BOUNDARY: 🔴 HEAVY CONTEXT", msg)
        self.assertIn("implementation_plan.md", msg)


if __name__ == "__main__":
    unittest.main()
