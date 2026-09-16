---
description: Universal context hygiene, token management, and multi-issue thread splitting
trigger: always_on
---

# Universal Context Hygiene & Task Handoff Guidelines

To maintain fast response latency, eliminate hallucinations from stale history, and maximize token efficiency across all projects and workflows (audits, features, live debugging, and support hotlines):

## 1. Universal Conversation Depth Limit (>30–40 Turns or >60k Tokens)
Regardless of the task type:
- **Continuous Monitoring**: Whenever a conversation exceeds **30–40 turns** or context reaches **>60k tokens**, the agent MUST actively manage context bloat.
- **Milestone & Phase Checkpoint**: Upon completing any substantial investigation, fix, or verification step in a heavy thread, the agent MUST summarize critical invariants and state into an artifact (`walkthrough.md`, `implementation_plan.md`, or an ADR doc).
- **Mandatory Handoff Advisory**: Append a concise Context Health notice offering the user:
  1. Quick follow-up in the current thread, OR
  2. A fresh, clean conversation using an anchored handoff prompt.

## 2. Multi-Issue Topic Shift Detection
In live debugging, hotline, or support sessions where multiple distinct issues arise sequentially:
- **Do NOT accumulate unrelated bugs in one mega-thread**: When Issue A is resolved/verified and a new distinct topic, bug, or subsystem (Issue B) is introduced:
  - Summarize the resolution of Issue A into an artifact.
  - Proactively advise splitting: *"Issue A is resolved and documented. Since this conversation has substantial history, I recommend opening a fresh thread for Issue B to keep latency fast and prevent context pollution."*
  - Provide a ready-to-use anchored prompt for Issue B.

## 3. Lossless Handoff Pattern
Every handoff advisory MUST be lossless, containing:
- Direct link to the specification/summary artifact (`@[file:path/to/artifact.md]`)
- Links to exact target code files (`@[file:path/to/target]`)
- Reference to the parent conversation (`@[conversation:"..."]`) for historical context on-demand.

## 4. Research & Exploration Delegation
- Delegate broad searches across dozens of files to a `research` subagent (`invoke_subagent`).
- The subagent explores in an isolated context and returns only concise technical findings, protecting the main conversation from hundreds of thousands of raw file tokens.
