---
name: context-steward
description: Monitor context size, execute lossless milestone handoffs, and manage token hygiene across conversations.
---

# Context Steward Skill

This skill guides the agent on how to manage context size, detect token bloating, and execute clean, lossless task handoffs across any project.

## When to Activate
- When a task reaches a natural milestone (e.g. audit finished, design doc approved, component verified).
- When a conversation exceeds 30–40 turns or context begins to feel heavy.
- When the user asks about context usage, token optimization, or task delegation.

## Tools & Utilities
- Run `python ~/.gemini/config/skills/context-steward/scripts/count_tokens.py --health` to quickly check the active conversation's context health badge.
- Run `python ~/.gemini/config/skills/context-steward/scripts/count_tokens.py <CONV_ID> --handoff` to automatically extract artifacts and modified files into an anchored, ready-to-copy lossless handoff prompt.
- Run `python ~/.gemini/config/skills/context-steward/scripts/count_tokens.py <CONV_ID> --details` for a full turn-by-turn breakdown.

## Lossless Handoff Recipe
Before suggesting a thread split:
1. **Freeze Findings in an Artifact**:
   - Write all architectural constraints, edge cases, target interfaces, and invariants into a dedicated markdown artifact (`implementation_plan.md` or ADR).
2. **Formulate the Handoff Anchor**:
   - Run `count_tokens.py <CONV_ID> --handoff` or provide a prompt the user can copy-paste into a fresh conversation:
     ```text
     Please implement [Milestone Name] according to the specification in @[file:path/to/spec.md].
     Primary code files: @[file:path/to/file1], @[file:path/to/file2].
     Reference parent conversation: @[conversation:"Parent Conversation Title"].
     ```

## Key Optimization Anti-Patterns to Avoid
1. **Exploratory Spikes in Main Thread**: Never run dozens of iterative `view_file` and `grep_search` calls across multiple subsystems directly in the main thread. Delegate discovery spikes to a `research` subagent to absorb file tokens in an ephemeral sandbox.
2. **Monolithic File Ingestion**: Never view large files (>50 KB) repeatedly in full. Use narrow line ranges or subagent delegation.
3. **Execution in Bloated Planning Threads**: When an implementation plan is authored in a thread that has already accumulated significant history (>40k tokens), do NOT proceed with code modifications in that thread. Execute the plan via a fresh thread or subagent.

