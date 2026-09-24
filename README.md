# Antigravity Context Hygiene & Token Steward

A global customization bundle for Google Antigravity to maintain lean context windows, maximize prompt caching hit rates, avoid attention degradation, and track exact token metrics across conversations.

---

## What's Included

* **`hooks.json` & `skills/context-steward/scripts/health_hook.py`**: A native Antigravity `PreInvocation` lifecycle hook that automatically checks context health on every model call. When a thread reaches `🔴 HEAVY` (>60k tokens or >30 turns), it injects an ephemeral system alert prompting the agent to provide a lossless handoff.
* **`rules/context_hygiene.md`**: An always-on Antigravity rule that automatically prompts the agent to freeze findings into rich technical artifacts (`implementation_plan.md` or ADR) at major milestone boundaries and offer clean thread handoffs.
* **`skills/context-steward/SKILL.md`**: A skill teaching the agent lossless handoff patterns and delegation workflows.
* **`skills/context-steward/scripts/count_tokens.py`**: A standalone zero-dependency Python script that parses conversation SQLite databases and protobuf metadata to report:
  - Uncached prompt tokens vs. cached tokens & cache hit rate (%).
  - Thinking / reasoning tokens vs. generation tokens.
  - Context size health status (`🟢 LEAN`, `🟡 MODERATE`, `🔴 HEAVY`).
  - Phase-by-phase breakdown per user request.

---

## Installation via Symlinks / Hardlinks

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
Remove-Item -Force -Recurse -ErrorAction SilentlyContinue "$HOME\.gemini\config\hooks.json"

# Create symbolic links (or hardlink for hooks.json)
New-Item -ItemType SymbolicLink -Path "$HOME\.gemini\config\rules\context_hygiene.md" -Target "$RepoRoot\rules\context_hygiene.md"
New-Item -ItemType SymbolicLink -Path "$HOME\.gemini\config\skills\context-steward" -Target "$RepoRoot\skills\context-steward"
New-Item -ItemType HardLink -Path "$HOME\.gemini\config\hooks.json" -Target "$RepoRoot\hooks.json"
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
```
