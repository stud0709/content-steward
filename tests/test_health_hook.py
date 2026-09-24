#!/usr/bin/env python3
"""
Test Suite for Transition-Boundary-Aware Context Health Hook
============================================================
Tests:
- Unit parsing and helper functions (is_execution_command, step slicing, artifact detection)
- Error handling on malformed/empty stdin
- Real conversation 82061474-e281-4a81-a2eb-73c9a7af8842:
  * step 550: in-progress Q&A inquiry -> quiet telemetry mode (no handoff prompt)
  * step 558: transition boundary after write_to_file implementation_plan.md -> full handoff prompt
  * direct end-of-transcript pipe invocation
- Boundary logic on execution approval commands
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

    def test_is_execution_command_positive(self):
        positive_samples = [
            "proceed",
            "go ahead",
            "implement",
            "start",
            "approved",
            "approve",
            "yes",
            "do it",
            "please proceed",
            "go ahead and implement",
            "lets go",
            "let's go",
            "execute",
            "lgtm",
            "looks good",
            "sounds good proceed",
            "<USER_REQUEST>\nproceed\n</USER_REQUEST>",
            "<USER_REQUEST>\n  go ahead  \n</USER_REQUEST>",
        ]
        for sample in positive_samples:
            self.assertTrue(
                health_hook.is_execution_command(sample),
                f"Expected '{sample}' to be recognized as execution command",
            )

    def test_is_execution_command_negative(self):
        negative_samples = [
            'are "banned / blocked / rate-limited" standard values or does every server send whatever it wants?',
            "is this implemented?",
            "what is the difference between X and Y?",
            "can we test this?",
            "why did the test fail?",
            "make a plan",
            "where is the config file located?",
            "how does NIP-20 work?",
            "",
            "   ",
            "<USER_REQUEST>\nis this working?\n</USER_REQUEST>",
        ]
        for sample in negative_samples:
            self.assertFalse(
                health_hook.is_execution_command(sample),
                f"Expected '{sample}' NOT to be recognized as execution command",
            )

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

    def test_empty_and_invalid_payloads(self):
        # Empty dict
        out = self._run_hook({})
        self.assertEqual(out, {})

        # Unknown conversation ID
        out = self._run_hook({"conversationId": "00000000-0000-0000-0000-000000000000"})
        self.assertEqual(out, {})

    def test_real_conversation_step_550_qa_quiet_mode(self):
        """
        Step 550 of 82061474 is an in-progress Q&A inquiry:
        User asks: 'are "banned / blocked / rate-limited" standard values...'
        Expects:
        - Output is valid PreInvocation JSON.
        - injectSteps contains quiet telemetry advisory.
        - Mentions '🔴 HEAVY' and 'Do NOT nag the user'.
        - Does NOT contain handoff prompt ('Please implement...').
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

    def test_real_conversation_step_558_transition_boundary(self):
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

    def test_real_conversation_direct_invocation(self):
        """Tests health_hook.py without stepIdx (evaluates end of transcript)."""
        out = self._run_hook({"conversationId": REAL_CONV_ID})
        self.assertIn("injectSteps", out)
        steps = out["injectSteps"]
        self.assertEqual(len(steps), 1)
        msg = steps[0].get("ephemeralMessage", "")
        self.assertIn("[TRANSITION BOUNDARY: 🔴 HEAVY CONTEXT", msg)
        self.assertIn("implementation_plan.md", msg)

    def test_execution_approval_boundary(self):
        """
        Tests Condition B (Execution Approval Boundary):
        User says 'proceed' when implementation_plan.md exists.
        Expects:
        - Output is valid PreInvocation JSON.
        - injectSteps contains execution boundary warning.
        - Mentions 'The user requested execution, but this conversation is 🔴 HEAVY'.
        - Instructs model to delegate to worker subagent or launch fresh thread.
        - Contains embedded Lossless Handoff prompt.
        """
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8") as tf:
            tf.write(json.dumps({
                "step_index": 1,
                "source": "USER_EXPLICIT",
                "type": "USER_INPUT",
                "content": "<USER_REQUEST>\nproceed\n</USER_REQUEST>"
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
            self.assertIn("[EXECUTION BOUNDARY IN 🔴 HEAVY CONTEXT", msg)
            self.assertIn("The user requested execution, but this conversation is 🔴 HEAVY", msg)
            self.assertIn("package the scope into an Execution Packet and immediately delegate to a worker subagent", msg)
            self.assertIn("Please implement NIP-20 Prefix-Aware Reactive Backoff & Circuit Breaker", msg)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


if __name__ == "__main__":
    unittest.main()
