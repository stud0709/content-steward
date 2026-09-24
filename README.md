# Antigravity Context Hygiene & Token Steward

A global customization bundle for Google Antigravity to maintain lean context windows, maximize prompt caching hit rates, avoid attention degradation, and track exact token metrics across conversations.

---

## What's Included

* **`hooks.json` & `skills/context-steward/scripts/health_hook.py`**: A transition-boundary-aware Antigravity `PreInvocation` lifecycle hook that enforces context hygiene without nagging:
  - **`🟢 LEAN` (<40k tokens & <20 turns)**: Completely silent (`{}`).
  - **Transition Boundary (Artifact Written)**: Triggered immediately when `implementation_plan.md` or `walkthrough.md` is authored in a `🔴 HEAVY` (>60k-80k tokens) or deep `🟡 MODERATE` (turns >= 25) thread. Injects a ready-to-copy **Lossless Handoff block** with file anchors and parent conversation citations so execution starts fresh.
  - **Execution Approval Boundary**: Triggered when the user submits an execution command (`proceed`, `go ahead`, `implement`, `start`, `approved`, `yes`, `do it`, etc.) against an existing plan in a `🔴 HEAVY` thread. Instructs the model to recommend a fresh chat or strictly delegate code modifications to a worker subagent.
  - **In-Progress Q&A / Active Turns**: Suppresses handoff blocks entirely and injects a quiet context telemetry reminder instructing the model not to nag the user during normal conversational inquiry.
* **`rules/context_hygiene.md`**: An always-on Antigravity rule establishing universal conversation depth thresholds, delegation boundaries, and handoff protocols.
* **`skills/context-steward/SKILL.md`**: A skill teaching the agent lossless handoff patterns and delegation workflows.
* **`skills/context-steward/scripts/count_tokens.py`**: A standalone zero-dependency Python script that parses conversation SQLite databases and protobuf metadata to report:
  - Uncached prompt tokens vs. cached tokens & cache hit rate (%).
  - Thinking / reasoning tokens vs. generation tokens.
  - Context size health status (`🟢 LEAN`, `🟡 MODERATE`, `🔴 HEAVY`).
  - Phase-by-phase breakdown per user request.
  - Automated Lossless Handoff prompt generation via `--handoff`.
* **`tests/test_health_hook.py`**: Unit and integration test suite asserting PreInvocation schema compliance, boundary detection, and regression verification against historical transcripts.

---

## Installation via Symlinks

Clone this repository to your preferred location (e.g., `$HOME\git\antigravity-context-hygiene`), then run the following in PowerShell:

```powershell
# Define path to where you cloned this repository
$RepoRoot = "$HOME\git\antigravity-context-hygiene"

# Ensure target directories exist in $HOME\.gemini
New-Item -ItemType Directory -Force -Path "$HOME\.gemini\config\rules" | Out-Null
New-Item -ItemType Directory -Force -Path "$HOME\.gemini\config\skills" | Out-Null

# Remove existing files/folders if present
Remove-Item -Force -Recurse -ErrorAction SilentlyContinue "$HOME\.gemini\config\rules\context_hygiene.md"
Remove-Item -Force -Recurse -ErrorAction SilentlyContinue "$HOME\.gemini\config\skills\context-steward"
Remove-Item -Force -ErrorAction SilentlyContinue "$HOME\.gemini\config\hooks.json"

# Create symbolic links
New-Item -ItemType SymbolicLink -Path "$HOME\.gemini\config\rules\context_hygiene.md" -Target "$RepoRoot\rules\context_hygiene.md"
New-Item -ItemType SymbolicLink -Path "$HOME\.gemini\config\skills\context-steward" -Target "$RepoRoot\skills\context-steward"
New-Item -ItemType SymbolicLink -Path "$HOME\.gemini\config\hooks.json" -Target "$RepoRoot\hooks.json"
```

---

## Quick Usage

```bash
# Check context health of current active conversation:
python ~/.gemini/config/skills/context-steward/scripts/count_tokens.py --health

# Analyze a conversation by title keyword or UUID:
python ~/.gemini/config/skills/context-steward/scripts/count_tokens.py "Warehouse Monitor"
python ~/.gemini/config/skills/context-steward/scripts/count_tokens.py <CONVERSATION_UUID> --details

# Generate an anchored Lossless Handoff prompt for a fresh conversation:
python ~/.gemini/config/skills/context-steward/scripts/count_tokens.py <CONVERSATION_UUID> --handoff

# List recent conversations:
python ~/.gemini/config/skills/context-steward/scripts/count_tokens.py --list

# Run health hook test suite:
python tests/test_health_hook.py
```
