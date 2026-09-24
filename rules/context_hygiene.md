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
- **Automated Handoff Generation Mandate**: Whenever finalizing a `walkthrough.md`, completing a plan verification in a `🟡 MODERATE`/`🔴 HEAVY` thread, or upon receiving a `[CONTEXT HEALTH ALERT: 🔴 HEAVY]` hook notice:
  1. You MUST execute: `python ~/.gemini/config/skills/context-steward/scripts/count_tokens.py --handoff`
  2. You MUST append the stdout (the ready-to-copy Lossless Handoff block) verbatim to the bottom of your response.

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
- **Exploratory Spike Threshold**: When investigating an issue spanning multiple subsystems (e.g., Domain -> Server -> Client -> Presentation) or requiring iterative searching across files, delegate the spike to a `research` subagent (`invoke_subagent`).
- **Hard Cap on In-Thread Research**: If an investigation, bug audit, or codebase search requires **>3 search/read tool calls** or touches **>2 files**, you MUST NOT continue exploratory searching in the main thread. Immediately dispatch a `research` subagent (`Model: 'flash'`) to absorb the file tokens and return concise architectural findings. Never accumulate dozens of `view_file` and `grep_search` calls in the parent context.
- **Monolithic File Ingestion**: Files >50 KB (e.g., god-controllers, large client sync classes) MUST NEVER be repeatedly read in full or large slices in the main thread. Use narrow line slicing (`StartLine`/`EndLine`), symbol lookups, or delegate code tracing to a subagent.

## 5. Planning Phase Boundary Handoff
Authoring an `implementation_plan.md` represents the cleanest transition boundary in software workflows (Discovery -> Execution):
- Whenever an implementation plan is authored in a conversation that is already **🟡 MODERATE** or **🔴 HEAVY** (>25–30 turns or >40k tokens), the agent MUST treat planning as a phase boundary.
- Do NOT begin executing code edits directly in that bloated thread.
- Automatically present the approved plan alongside a ready-to-copy **Lossless Handoff prompt** (or launch execution in an isolated subagent) so coding and verification begin in a lean, high-speed context (`🟢 LEAN`).
- **Handoff Execution Invariant**: When a fresh conversation is started via a Lossless Handoff prompt with an approved specification/plan, or when the user prompts "proceed" on an approved plan, the orchestrator MUST NOT execute code edits, run build/test commands, or repeatedly inspect files directly in the main thread. It must immediately package the scope into an Execution Packet (§ 6.D) and dispatch the worker subagent.

## 6. Proactive Execution Delegation & Dynamic Model Routing
To prevent the main conversation from degrading during iterative code modifications, compiling, and testing loops:

### A. Execution Fast-Path vs. Mandatory Subagent Delegation
- **In-Thread Fast Path (Allowed)**:
  - Edits affecting **$\le 1$ file**, **$< 30$ lines**, with **deterministic outcomes** (e.g., updating a config, fixing an obvious typo, adding a missing import or type annotation) MAY be executed directly in the main thread provided the thread is `🟢 LEAN`.
- **Mandatory Subagent Delegation**:
  - You MUST delegate execution to a subagent (`invoke_subagent`) when:
    1. The change spans **$\ge 2$ files**.
    2. The fix requires an **iterative test / verify / debug loop** (running test suites, interpreting compiler errors, adjusting assertions).
    3. The task involves a complex refactor or algorithmic rewrite.
- **Follow-Up Re-evaluation (Zero Creep)**:
  - Follow-up turns within an existing thread are strictly bound by the same delegation thresholds. If a follow-up request (e.g., adding a button, tweaking a handler) requires searching >2 files, modifying $\ge 2$ files, or running verification/service restart loops, it MUST NOT remain in the main thread. Delegate the task to a subagent to prevent incremental context creep.

### B. Dynamic Model Selection Matrix
Before delegating, inspect target code ($\le 2$ files) to assess complexity and pass the optimal `Model` tier to `invoke_subagent`:

| Task Profile / Complexity Signals | Model Tier | Workspace Mode | Role / Pattern |
| :--- | :--- | :--- | :--- |
| **Exploration & Scaffolding**<br>• Searching >3 files or repo-wide scans<br>• Extracting API schemas / call graphs<br>• Summarizing documentation or dependencies | `flash` *(or `flash_lite`)* | `inherit` | `research` subagent |
| **Deterministic / Low-Risk Execution**<br>• Straightforward multi-file boilerplate or CRUD<br>• Adding tests against an already green test harness<br>• Standard library or routine framework updates | `flash` | `inherit` *(active dev)* | `self` subagent |
| **Deep Agentic Reasoning & Debugging**<br>• Race conditions, async timing, or memory leaks<br>• Intricate cross-package refactoring<br>• Writing reproduction harnesses for elusive bugs | `pro` *(or `inherit`)* | `inherit` *(active dev)* | `self` subagent |
| **Speculative / High-Risk Experiments**<br>• Experimental architectural spikes<br>• Potentially destructive git/file modifications | `flash` or `pro` | `branch` *(isolated)* | `self` subagent |

### C. Workspace Mode Policy (`inherit` vs `branch`)
- **`Workspace: "inherit"` (Default for Active Pair Programming)**:
  - Applies file edits directly to the user's working tree so changes and test results are immediately visible in the active workspace. Use this for standard features, fixes, and tests.
- **`Workspace: "branch"` (Isolated Sandbox)**:
  - Isolates filesystem edits into an ephemeral git branch. Use ONLY for speculative spikes or high-risk tests where you explicitly do not want unverified code touching the working tree.

### D. The Structured Execution Packet (Preventing Amnesia & Read Churn)
Because subagents do NOT inherit parent conversation history, every delegation prompt MUST provide a self-contained execution packet:

1. **Target Files & Scope Granularity ($\le 3–5$ Files per Worker)**:
   - Explicit file paths demarcated with `[NEW]` and `[MODIFY]`.
   - Never dump dozens of files across multiple unrelated bug categories (e.g., 10–20 files) onto a single worker subagent; doing so causes pre-flight read churn. Decompose large plans into cohesive clusters of **$\le 3–5$ files** per worker.
2. **Context & Technical Spec**: Exact design spec, structs, schemas, or suspected root cause.
3. **Contract Reference Anchors**:
   - Never leave internal API signatures or database patterns underspecified.
   - Always supply 1–2 file and line anchors to existing implementations (e.g., `DB connection pattern: handlers/logs.go#L25-L45`, `Discovery struct: adt/session.go#L140-L160`) so the worker does not run broad repository greps or scan dependencies.
4. **Mandatory Worker Directives (Embed in Subagent Prompt)**:
   - **Suppress Meta-Planning**: *"Planning is already completed and approved in the parent conversation. Do NOT author an implementation plan or design document; proceed directly to implementation."*
   - **Staged Phasing (Logic $\rightarrow$ Verify $\rightarrow$ Docs)**: *"Do NOT read documentation templates or secondary markdown files up-front. Implement core code, verify with test commands, and only inspect/edit documentation templates once all tests pass."*
   - **Targeted Grounding**: *"Do NOT run broad repository scans or read whole files. Read only the specific line anchors provided to verify types."*
5. **Concrete Acceptance Criteria**: Exact terminal commands to verify (e.g., `npm test`, `go test ./...`, or build scripts).
6. **Auto-Escalation**: If a `flash` subagent fails verification after 2 iterations, abort the worker and re-dispatch the failure trace to a `pro` subagent.

