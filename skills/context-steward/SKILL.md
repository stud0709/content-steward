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
- Run `python ~/.gemini/config/skills/context-steward/scripts/count_tokens.py <CONV_ID> --details` for a full turn-by-turn breakdown.

## Lossless Handoff Recipe
Before suggesting a thread split:
1. **Freeze Findings in an Artifact**:
   - Write all architectural constraints, edge cases, target interfaces, and invariants into a dedicated markdown artifact (`implementation_plan.md` or ADR).
2. **Formulate the Handoff Anchor**:
   - Give the user a concrete prompt they can copy-paste into a fresh conversation:
     ```text
     Please implement [Milestone Name] according to the specification in @[file:path/to/spec.md].
     Primary code files: @[file:path/to/file1], @[file:path/to/file2].
     Reference parent conversation: @[conversation:"Parent Conversation Title"].
     ```
