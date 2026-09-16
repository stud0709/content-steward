#!/usr/bin/env python3
"""
Antigravity Conversation Token Counter & Context Health Monitor
===============================================================
Calculates token metrics and monitors context health / split recommendations
for Antigravity conversations across all workspaces.

Usage:
    python count_tokens.py [CONVERSATION_ID_OR_TITLE_OR_PATH] [OPTIONS]

Examples:
    python count_tokens.py --health          # Check health of current/latest conversation
    python count_tokens.py "Warehouse Monitor Custom Button"
    python count_tokens.py 6c379271 --details
    python count_tokens.py --list
    python count_tokens.py 6c379271 --json
"""

import argparse
import glob
import json
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# ==============================================================================
# Pure Python Protobuf Wire Decoder
# ==============================================================================

def decode_protobuf(data: bytes) -> List[Tuple[int, str, Any]]:
    """Decodes raw protobuf bytes into a list of (field_number, wire_type, value)."""
    pos = 0
    res = []
    while pos < len(data):
        shift = 0
        tag = 0
        while True:
            if pos >= len(data):
                return res
            b = data[pos]
            pos += 1
            tag |= (b & 0x7F) << shift
            shift += 7
            if not (b & 0x80):
                break

        field_num = tag >> 3
        wire_type = tag & 7

        if wire_type == 0:  # Varint
            val = 0
            shift = 0
            while True:
                if pos >= len(data):
                    break
                b = data[pos]
                pos += 1
                val |= (b & 0x7F) << shift
                shift += 7
                if not (b & 0x80):
                    break
            res.append((field_num, 'varint', val))

        elif wire_type == 1:  # 64-bit
            val = data[pos:pos + 8]
            pos += 8
            res.append((field_num, '64-bit', val))

        elif wire_type == 2:  # Length-delimited
            length = 0
            shift = 0
            while True:
                if pos >= len(data):
                    break
                b = data[pos]
                pos += 1
                length |= (b & 0x7F) << shift
                shift += 7
                if not (b & 0x80):
                    break
            val_bytes = data[pos:pos + length]
            pos += length

            try:
                s = val_bytes.decode('utf-8')
                if all(c.isprintable() or c in '\n\r\t' for c in s) and len(s) > 0:
                    res.append((field_num, 'string', s))
                else:
                    sub = decode_protobuf(val_bytes)
                    if sub and len(sub) > 0:
                        res.append((field_num, 'message', sub))
                    else:
                        res.append((field_num, 'bytes', val_bytes))
            except Exception:
                sub = decode_protobuf(val_bytes)
                if sub and len(sub) > 0:
                    res.append((field_num, 'message', sub))
                else:
                    res.append((field_num, 'bytes', val_bytes))

        elif wire_type == 5:  # 32-bit
            val = data[pos:pos + 4]
            pos += 4
            res.append((field_num, '32-bit', val))
        else:
            res.append((field_num, f'unknown_{wire_type}', data[pos:]))
            break
    return res


# ==============================================================================
# Path & Discovery Utilities
# ==============================================================================

def get_search_directories() -> List[Path]:
    """Returns candidate directories where Antigravity stores data."""
    home = Path.home()
    dirs = [
        home / ".gemini" / "antigravity",
        home / ".gemini" / "antigravity-ide",
    ]
    app_data = os.environ.get("ANTIGRAVITY_APP_DATA")
    if app_data:
        dirs.insert(0, Path(app_data))
    return [d for d in dirs if d.exists()]


def get_latest_conversation_db(search_dirs: List[Path]) -> Optional[Path]:
    """Finds the most recently modified conversation DB."""
    dbs = []
    for base in search_dirs:
        conv_dir = base / "conversations"
        if conv_dir.exists():
            dbs.extend(conv_dir.glob("*.db"))
    if not dbs:
        return None
    return max(dbs, key=lambda p: p.stat().st_mtime)


def get_conversation_title(conv_id: str, search_dirs: List[Path]) -> Optional[str]:
    """Extracts conversation title from annotations or summary DB if available."""
    for base in search_dirs:
        annot_file = base / "annotations" / f"{conv_id}.pbtxt"
        if annot_file.exists():
            try:
                content = annot_file.read_text(encoding="utf-8", errors="ignore")
                match = re.search(r'title\s*:\s*"([^"]+)"', content)
                if match:
                    return match.group(1)
            except Exception:
                pass

        plan_file = base / "brain" / conv_id / "implementation_plan.md"
        if plan_file.exists():
            try:
                for line in plan_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                    if line.startswith("# "):
                        return line.lstrip("# ").strip()
            except Exception:
                pass
    return None


def list_conversations(search_dirs: List[Path], limit: int = 25) -> List[Dict[str, Any]]:
    """Lists conversations sorted by modification time."""
    results = []
    seen_ids = set()

    for base in search_dirs:
        conv_dir = base / "conversations"
        if not conv_dir.exists():
            continue
        for db_file in conv_dir.glob("*.db"):
            conv_id = db_file.stem
            if conv_id in seen_ids:
                continue
            seen_ids.add(conv_id)

            mtime = db_file.stat().st_mtime
            dt_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
            title = get_conversation_title(conv_id, search_dirs) or "(Untitled Conversation)"

            results.append({
                "id": conv_id,
                "title": title,
                "mtime": mtime,
                "date": dt_str,
                "db_path": str(db_file),
                "base_dir": str(base),
            })

    results.sort(key=lambda x: x["mtime"], reverse=True)
    return results[:limit]


def find_conversation_db(target: Optional[str], search_dirs: List[Path]) -> Tuple[Optional[Path], Optional[str]]:
    """Resolves target string (UUID, prefix, title, or direct path) or picks latest if None."""
    if not target:
        latest = get_latest_conversation_db(search_dirs)
        if latest:
            return latest, get_conversation_title(latest.stem, search_dirs)
        return None, None

    p = Path(target)
    if p.exists() and p.is_file():
        return p, get_conversation_title(p.stem, search_dirs)

    target_clean = target.strip().lower()

    # 1. Exact UUID match
    for base in search_dirs:
        db = base / "conversations" / f"{target_clean}.db"
        if db.exists():
            return db, get_conversation_title(target_clean, search_dirs)

    # 2. Prefix UUID match
    for base in search_dirs:
        conv_dir = base / "conversations"
        if conv_dir.exists():
            matches = list(conv_dir.glob(f"{target_clean}*.db"))
            if len(matches) == 1:
                return matches[0], get_conversation_title(matches[0].stem, search_dirs)
            elif len(matches) > 1:
                print(f"Ambiguous conversation prefix '{target}'. Multiple matches found:")
                for m in matches:
                    t = get_conversation_title(m.stem, search_dirs) or "(Untitled)"
                    print(f"  * {m.stem} ({t})")
                return None, None

    # 3. Search by title / annotations keyword
    candidates = []
    for base in search_dirs:
        annot_dir = base / "annotations"
        if annot_dir.exists():
            for pbtxt in annot_dir.glob("*.pbtxt"):
                try:
                    content = pbtxt.read_text(encoding="utf-8", errors="ignore")
                    m = re.search(r'title\s*:\s*"([^"]+)"', content)
                    if m and target_clean in m.group(1).lower():
                        conv_id = pbtxt.stem
                        db_path = base / "conversations" / f"{conv_id}.db"
                        if db_path.exists():
                            candidates.append((db_path, m.group(1)))
                except Exception:
                    pass

    if len(candidates) == 1:
        return candidates[0]
    elif len(candidates) > 1:
        print(f"Multiple conversations match title keyword '{target}':")
        for db_p, t in candidates:
            print(f"  * {db_p.stem} -> \"{t}\"")
        return None, None

    return None, None


# ==============================================================================
# Token & Health Analysis
# ==============================================================================

def clean_prompt_snippet(raw_text: str, max_len: int = 70) -> str:
    """Cleans up raw prompt content to remove XML tags and format nicely."""
    cleaned = re.sub(r'<[^>]+>', ' ', raw_text)
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    snippet = lines[0] if lines else "(Empty Prompt)"
    if len(snippet) > max_len:
        snippet = snippet[:max_len - 3] + "..."
    return snippet


def analyze_conversation_tokens(db_path: Path, search_dirs: List[Path]) -> Dict[str, Any]:
    """Parses generation metadata and calculates detailed token metrics."""
    conv_id = db_path.stem
    title = get_conversation_title(conv_id, search_dirs) or "(Untitled)"

    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()

    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='gen_metadata';")
    if not c.fetchone():
        return {
            "id": conv_id,
            "title": title,
            "error": "No generation metadata table found in conversation DB.",
        }

    c.execute("SELECT idx, data FROM gen_metadata ORDER BY idx;")
    rows = c.fetchall()
    conn.close()

    if not rows:
        return {
            "id": conv_id,
            "title": title,
            "error": "No generation turns recorded in conversation DB.",
        }

    turns = []
    models_used = set()

    for idx, data in rows:
        parsed = decode_protobuf(data)
        f1_matches = [v for k, t, v in parsed if k == 1]
        if not f1_matches:
            continue
        f1 = f1_matches[0]

        model_names = [v for k, t, v in f1 if k == 19]
        model = model_names[0] if model_names else "unknown"
        models_used.add(model)

        meta_kvs = {item[2][0][2]: item[2][1][2] for item in f1 if item[0] == 20 and len(item[2]) >= 2}
        step_idx = int(meta_kvs.get("last_step_index", -1))

        f4_matches = [v for k, t, v in f1 if k == 4]
        if not f4_matches:
            continue
        f4_dict = {k: v for k, t, v in f4_matches[0]}

        uncached_input = f4_dict.get(2, 0)
        cached_input = f4_dict.get(5, 0)
        total_input = uncached_input + cached_input

        total_output = f4_dict.get(3, 0)
        thinking_tokens = f4_dict.get(9, 0)
        response_tokens = f4_dict.get(10, 0)

        f9_input = 0
        f9_matches = [v for k, t, v in f1 if k == 9]
        if f9_matches:
            f9_dict = {k: v for k, t, v in f9_matches[0]}
            if 10 in f9_dict and isinstance(f9_dict[10], list):
                f10_sub = {k: v for k, t, v in f9_dict[10]}
                f9_input = f10_sub.get(1, 0)

        turns.append({
            "turn_idx": idx,
            "step_idx": step_idx,
            "model": model,
            "uncached_input": uncached_input,
            "cached_input": cached_input,
            "total_input": total_input,
            "raw_context_input": f9_input,
            "thinking_output": thinking_tokens,
            "response_output": response_tokens,
            "total_output": total_output,
            "turn_total": total_input + total_output,
        })

    # Read user prompts
    user_prompts = []
    for base in search_dirs:
        transcript_full = base / "brain" / conv_id / ".system_generated" / "logs" / "transcript_full.jsonl"
        if transcript_full.exists():
            try:
                with open(transcript_full, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        d = json.loads(line)
                        if d.get("type") == "USER_INPUT":
                            user_prompts.append({
                                "step_index": d.get("step_index", 0),
                                "content": d.get("content", "").strip(),
                            })
                break
            except Exception:
                pass

    filtered_prompts = []
    for up in user_prompts:
        if not filtered_prompts or up["step_index"] != filtered_prompts[-1]["step_index"]:
            filtered_prompts.append(up)

    phases = []
    if filtered_prompts:
        for i, up in enumerate(filtered_prompts):
            sidx = up["step_index"]
            next_sidx = filtered_prompts[i + 1]["step_index"] if i + 1 < len(filtered_prompts) else 999999
            phase_turns = [t for t in turns if sidx <= t["step_idx"] < next_sidx]
            prompt_snippet = clean_prompt_snippet(up["content"], max_len=75)

            phases.append({
                "phase_num": i + 1,
                "step_index": sidx,
                "prompt_snippet": prompt_snippet,
                "turns_count": len(phase_turns),
                "uncached_input": sum(t["uncached_input"] for t in phase_turns),
                "cached_input": sum(t["cached_input"] for t in phase_turns),
                "total_input": sum(t["total_input"] for t in phase_turns),
                "thinking_output": sum(t["thinking_output"] for t in phase_turns),
                "response_output": sum(t["response_output"] for t in phase_turns),
                "total_output": sum(t["total_output"] for t in phase_turns),
                "total_tokens": sum(t["turn_total"] for t in phase_turns),
            })

    total_uncached = sum(t["uncached_input"] for t in turns)
    total_cached = sum(t["cached_input"] for t in turns)
    total_input = sum(t["total_input"] for t in turns)
    total_thinking = sum(t["thinking_output"] for t in turns)
    total_response = sum(t["response_output"] for t in turns)
    total_output = sum(t["total_output"] for t in turns)
    grand_total = total_input + total_output
    billable_new = total_uncached + total_output

    cache_hit_rate = (total_cached / total_input * 100.0) if total_input > 0 else 0.0
    current_context = turns[-1]["total_input"] if turns else 0

    turns_count = len(turns)
    if current_context > 90000 or turns_count > 60:
        health_status = "HEAVY"
        health_color = "🔴"
        recommendation = (
            "Context is heavy (>90k tokens or >60 turns). Substantial history tax on every turn. "
            "Strongly recommended to document findings in a plan/artifact and split next task into a fresh chat."
        )
    elif current_context > 50000 or turns_count > 30:
        health_status = "MODERATE"
        health_color = "🟡"
        recommendation = (
            "Context is moderate (50k-90k tokens). Optimal for finishing the current milestone/component. "
            "Consider starting a new chat before starting an unrelated new feature."
        )
    else:
        health_status = "LEAN"
        health_color = "🟢"
        recommendation = "Context is lean and fast (<50k tokens). Ideal for continued iteration."

    return {
        "id": conv_id,
        "title": title,
        "db_path": str(db_path),
        "models": sorted(list(models_used)),
        "total_turns": turns_count,
        "current_context_tokens": current_context,
        "health": {
            "status": health_status,
            "badge": f"{health_color} {health_status}",
            "recommendation": recommendation,
        },
        "summary": {
            "uncached_input_tokens": total_uncached,
            "cached_input_tokens": total_cached,
            "total_input_tokens": total_input,
            "cache_hit_rate_pct": round(cache_hit_rate, 2),
            "thinking_output_tokens": total_thinking,
            "response_output_tokens": total_response,
            "total_output_tokens": total_output,
            "grand_total_tokens": grand_total,
            "billable_new_tokens": billable_new,
        },
        "averages_per_turn": {
            "avg_input": round(total_input / len(turns), 1) if turns else 0,
            "avg_uncached_input": round(total_uncached / len(turns), 1) if turns else 0,
            "avg_cached_input": round(total_cached / len(turns), 1) if turns else 0,
            "avg_output": round(total_output / len(turns), 1) if turns else 0,
            "avg_thinking": round(total_thinking / len(turns), 1) if turns else 0,
            "avg_response": round(total_response / len(turns), 1) if turns else 0,
        },
        "phases": phases,
        "turns": turns,
    }


# ==============================================================================
# Presentation & Formatting
# ==============================================================================

def print_health_badge(data: Dict[str, Any]):
    """Prints a quick single-card context health status."""
    if "error" in data:
        print(f"Error: {data['error']}")
        return

    health = data["health"]
    print("=" * 74)
    print(f" CONTEXT HEALTH: {health['badge']} | {data['title']}")
    print(f" ID: {data['id']}")
    print("=" * 74)
    print(f"  * Turns Count:         {data['total_turns']}")
    print(f"  * Current Context:     {data['current_context_tokens']:,} tokens")
    print(f"  * Total Processed:     {data['summary']['grand_total_tokens']:,} tokens")
    print(f"  * Prompt Cache Rate:   {data['summary']['cache_hit_rate_pct']}%")
    print("-" * 74)
    print(f" ADVICE: {health['recommendation']}")
    print("=" * 74)


def print_terminal_report(data: Dict[str, Any], show_details: bool = False):
    """Renders a clean, formatted report in the terminal."""
    if "error" in data:
        print(f"Error analyzing conversation '{data.get('id')}': {data['error']}")
        return

    summary = data["summary"]
    health = data["health"]

    print("=" * 74)
    print(f" TOKEN USAGE & HEALTH REPORT: {data['title']}")
    print(f" ID: {data['id']}")
    print("=" * 74)
    print(f"  * Health Status:       {health['badge']}")
    print(f"  * Models Used:         {', '.join(data['models'])}")
    print(f"  * Total Turns / Calls: {data['total_turns']}")
    print(f"  * Current Context Size:{data['current_context_tokens']:,} tokens")
    print(f"  * Cache Hit Rate:      {summary['cache_hit_rate_pct']}%")
    print("-" * 74)
    print(" INPUT TOKENS (Prompt Evaluation):")
    print(f"   - Newly Evaluated (Uncached):   {summary['uncached_input_tokens']:>12,}")
    print(f"   - Cached (Cache Read):          {summary['cached_input_tokens']:>12,}")
    print(f"   - Total Input Tokens:           {summary['total_input_tokens']:>12,}")
    print("-" * 74)
    print(" OUTPUT TOKENS (Completion Generation):")
    print(f"   - Thinking / Reasoning:         {summary['thinking_output_tokens']:>12,}")
    print(f"   - Response / Tool Calls:        {summary['response_output_tokens']:>12,}")
    print(f"   - Total Output Tokens:          {summary['total_output_tokens']:>12,}")
    print("-" * 74)
    print(" GRAND TOTALS:")
    print(f"   - Total Processed (Input + Out):{summary['grand_total_tokens']:>12,}")
    print(f"   - Net New Tokens (Uncached+Out):{summary['billable_new_tokens']:>12,}")
    print("-" * 74)
    print(f" GUIDANCE: {health['recommendation']}")
    print("=" * 74)

    if data["phases"]:
        print("\n PHASE BREAKDOWN:")
        print("-" * 74)
        for p in data["phases"]:
            print(f" Phase #{p['phase_num']} (Step {p['step_index']}): \"{p['prompt_snippet']}\"")
            print(f"   * Calls: {p['turns_count']:<3} | Total Input: {p['total_input']:>9,} (uncached: {p['uncached_input']:>7,}) | Output: {p['total_output']:>6,} (think: {p['thinking_output']:>5,})")
        print("-" * 74)

    if show_details and data["turns"]:
        print("\n TURN-BY-TURN DETAILS:")
        print("-" * 74)
        print(f" {'Turn':>4} | {'Step':>4} | {'Total In':>9} | {'Uncached':>8} | {'Cached':>8} | {'Output':>6} | {'Think':>5} | {'Resp':>5}")
        print("-" * 74)
        for t in data["turns"]:
            print(f" {t['turn_idx']:>4} | {t['step_idx']:>4} | {t['total_input']:>9,} | {t['uncached_input']:>8,} | {t['cached_input']:>8,} | {t['total_output']:>6,} | {t['thinking_output']:>5,} | {t['response_output']:>5,}")
        print("-" * 74)


# ==============================================================================
# Main Entry Point
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Calculate token usage and monitor context health for Antigravity conversations.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python count_tokens.py --health          # Check health of current conversation
  python count_tokens.py "Warehouse Monitor Custom Button"
  python count_tokens.py 6c379271 --details
  python count_tokens.py --list
  python count_tokens.py 6c379271 --json
        """,
    )

    parser.add_argument(
        "target",
        nargs="?",
        default=None,
        help="Conversation UUID, UUID prefix, title keyword, direct path, or omit for current/latest.",
    )
    parser.add_argument(
        "-l", "--list",
        action="store_true",
        help="List recent conversations with IDs and titles.",
    )
    parser.add_argument(
        "-H", "--health",
        action="store_true",
        help="Show concise Context Health badge and split recommendation.",
    )
    parser.add_argument(
        "-n", "--limit",
        type=int,
        default=25,
        help="Limit number of conversations listed (default: 25).",
    )
    parser.add_argument(
        "-d", "--details",
        action="store_true",
        help="Show detailed turn-by-turn breakdown.",
    )
    parser.add_argument(
        "-j", "--json",
        action="store_true",
        help="Output raw results in JSON format.",
    )

    args = parser.parse_args()
    search_dirs = get_search_directories()

    if not search_dirs:
        print("Error: No Antigravity directories found under ~/.gemini/", file=sys.stderr)
        sys.exit(1)

    if args.list:
        conversations = list_conversations(search_dirs, limit=args.limit)
        if args.json:
            print(json.dumps(conversations, indent=2))
        else:
            print("=" * 80)
            print(f" RECENT ANTIGRAVITY CONVERSATIONS (Top {len(conversations)})")
            print("=" * 80)
            print(f" {'Date / Time':<19} | {'Conversation ID':<36} | {'Title'}")
            print("-" * 80)
            for c in conversations:
                print(f" {c['date']:<19} | {c['id']:<36} | {c['title']}")
            print("-" * 80)
            print("To count tokens for a conversation, run:")
            print("  python count_tokens.py <ID_OR_TITLE>")
        return

    db_path, title = find_conversation_db(args.target, search_dirs)
    if not db_path:
        target_name = args.target if args.target else "latest"
        print(f"Error: Conversation matching '{target_name}' was not found.", file=sys.stderr)
        sys.exit(1)

    result = analyze_conversation_tokens(db_path, search_dirs)

    if args.json:
        print(json.dumps(result, indent=2))
    elif args.health:
        print_health_badge(result)
    else:
        print_terminal_report(result, show_details=args.details)


if __name__ == "__main__":
    main()
