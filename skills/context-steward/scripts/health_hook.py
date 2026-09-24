#!/usr/bin/env python3
"""
Antigravity PreInvocation Context Health Hook
=============================================
Executed by Antigravity runtime prior to model invocations.
Receives invocation context on stdin and injects an ephemeral
system warning when conversation context becomes 🔴 HEAVY (>60k-90k tokens or >30 turns).
"""

import json
import os
import sys
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

def main():
    try:
        raw_input = sys.stdin.read().strip()
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

        # Only inject alert if context is HEAVY or MODERATE with significant turns
        if status == "HEAVY":
            warning_msg = (
                f"[CONTEXT HEALTH ALERT: 🔴 HEAVY ({current_context:,} tokens in context, {total_turns} turns)]\n"
                f"Per Universal Context Hygiene Rules (§ 1 & § 2):\n"
                f"- This conversation has accumulated substantial history tax.\n"
                f"- If you are completing a milestone, updating walkthrough.md, or if the user is shifting to a new topic, "
                f"you MUST append a Lossless Handoff advisory block to this response so the user can continue in a fresh chat."
            )
            output = {
                "injectSteps": [
                    {
                        "ephemeralMessage": warning_msg
                    }
                ]
            }
            print(json.dumps(output))
            return
        elif status == "MODERATE" and total_turns >= 25:
            warning_msg = (
                f"[CONTEXT HEALTH NOTICE: 🟡 MODERATE ({current_context:,} tokens in context, {total_turns} turns)]\n"
                f"Approaching conversation depth threshold. Prepare to summarize and offer a Lossless Handoff upon completing this milestone."
            )
            output = {
                "injectSteps": [
                    {
                        "ephemeralMessage": warning_msg
                    }
                ]
            }
            print(json.dumps(output))
            return

        # Otherwise LEAN / early MODERATE -> Silent
        print("{}")
    except Exception:
        # Failsafe: never break the agent invocation
        print("{}")

if __name__ == "__main__":
    main()
