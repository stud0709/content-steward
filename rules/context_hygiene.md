---
description: Proactive context hygiene, milestone handoffs, and token management
trigger: always_on
---

# Context Hygiene & Task Handoff Guidelines

To maintain high reasoning accuracy, eliminate hallucinations from stale history, and optimize latency and token efficiency across all projects:

## 1. Milestone Checkpoints
When completing a major research, audit, or feature implementation milestone:
- **Produce a Rich Technical Artifact**: Summarize all critical technical invariants, discovered edge cases, and architectural constraints into an artifact (`implementation_plan.md`, `walkthrough.md`, or an ADR doc).
- **Proactively Advise on Context Handoff**: If the conversation has accumulated substantial history (>30–40 turns or >60k tokens), briefly notify the user at the end of the turn that they can either:
  1. Continue directly in the current conversation for quick follow-ups, OR
  2. Start a fresh, clean conversation referencing the newly created spec artifact for the next independent work package.

## 2. Research & Exploration Delegation
- When tasked with broad codebase exploration or scanning dozens of files, delegate to a `research` subagent (`invoke_subagent`).
- The subagent explores in an isolated branched context and returns only the concise technical findings, preventing hundreds of thousands of raw file tokens from polluting the main thread.

## 3. Lossless Handoff Pattern
When advising the user to start a new thread for a sub-task, provide them with a ready-to-use **anchored handoff prompt** that includes:
- Link to the specification artifact (`@[file:path/to/spec.md]`)
- Links to the exact target files (`@[file:path/to/target]`)
- Reference to the parent conversation (`@[conversation:"..."]`) for historical provenance if needed.
