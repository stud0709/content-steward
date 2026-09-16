# Antigravity Context Hygiene & Token Steward

A global customization bundle for Google Antigravity to maintain lean context windows, maximize prompt caching hit rates, avoid attention degradation, and track exact token metrics across conversations.

---

## What's Included

* **`rules/context_hygiene.md`**: An always-on Antigravity rule that automatically prompts the agent to freeze findings into rich technical artifacts (`implementation_plan.md` or ADR) at major milestone boundaries and offer clean thread handoffs.
* **`skills/context-steward/SKILL.md`**: A skill teaching the agent lossless handoff patterns and delegation workflows.
* **`skills/context-steward/scripts/count_tokens.py`**: A standalone zero-dependency Python script that parses conversation SQLite databases and protobuf metadata to report:
  - Uncached prompt tokens vs. cached tokens & cache hit rate (%).
  - Thinking / reasoning tokens vs. generation tokens.
  - Context size health status (`🟢 LEAN`, `🟡 MODERATE`, `🔴 HEAVY`).
  - Phase-by-phase breakdown per user request.

---

## Installation via Symlinks

Run the following in an **Elevated (Administrator) PowerShell**:

```powershell
# Ensure target directories exist
New-Item -ItemType Directory -Force -Path "$HOME\.gemini\config\rules" | Out-Null
New-Item -ItemType Directory -Force -Path "$HOME\.gemini\config\skills" | Out-Null

# Remove existing files/folders if present
Remove-Item -Force -Recurse -ErrorAction SilentlyContinue "$HOME\.gemini\config\rules\context_hygiene.md"
Remove-Item -Force -Recurse -ErrorAction SilentlyContinue "$HOME\.gemini\config\skills\context-steward"

# Create symbolic links
New-Item -ItemType SymbolicLink -Path "$HOME\.gemini\config\rules\context_hygiene.md" -Target "C:\Users\YuriyDzhenyeyev\git\antigravity-context-hygiene\rules\context_hygiene.md"
New-Item -ItemType SymbolicLink -Path "$HOME\.gemini\config\skills\context-steward" -Target "C:\Users\YuriyDzhenyeyev\git\antigravity-context-hygiene\skills\context-steward"
```

---

## Quick Usage

```bash
# Check context health of current active conversation:
python ~/.gemini/config/skills/context-steward/scripts/count_tokens.py --health

# Analyze a conversation by title keyword or UUID:
python ~/.gemini/config/skills/context-steward/scripts/count_tokens.py "Warehouse Monitor"
python ~/.gemini/config/skills/context-steward/scripts/count_tokens.py 6c379271 --details

# List recent conversations:
python ~/.gemini/config/skills/context-steward/scripts/count_tokens.py --list
```
