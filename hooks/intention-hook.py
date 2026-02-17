#!/home/neboo/elara-core/venv/bin/python3
# Copyright (c) 2026 Nenad Vasic. All rights reserved.
# Licensed under the Business Source License 1.1 (BSL-1.1)

"""
Intention Resolver — Claude Code UserPromptSubmit hook.

Runs before every user prompt. Enriches context by injecting a compact
system message with relevant corrections, workflows, goals, and handoff
items. Also absorbs Overwatch injection (replaces overwatch-inject.sh).

Design principles:
  - Zero LLM calls — only ChromaDB semantic search + file reads
  - Target output: 50-80 tokens (< 2% of context window)
  - Fail silent — any error = no injection, never block the prompt
  - Detect frustration signals for CompletionPattern learning

Output format (only non-empty sections appear):
  [CONTEXT] project | episode type
  [GOALS] goal1 | goal2
  [SELF-CHECK] mistake → correction
  [WORKFLOW] name: step1 → step2 → step3
  [CARRY-FORWARD] unfinished item | promise
  [OVERWATCH] (whatever Overwatch daemon left)
"""

import sys
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap: add elara-core to path, set data dir
# ---------------------------------------------------------------------------
ELARA_ROOT = Path("/home/neboo/elara-core")
sys.path.insert(0, str(ELARA_ROOT))
os.environ.setdefault("ELARA_DATA_DIR", str(Path.home() / ".claude"))

# Completion patterns file (accumulated frustration-derived learning)
PATTERNS_FILE = Path.home() / ".claude" / "elara-completion-patterns.json"

# Frustration signal regexes (compiled once)
FRUSTRATION_SIGNALS = [
    re.compile(r"\bbut you didn'?t\b", re.IGNORECASE),
    re.compile(r"\byou forgot\b", re.IGNORECASE),
    re.compile(r"\bi told you to\b", re.IGNORECASE),
    re.compile(r"\bwhy didn'?t you\b", re.IGNORECASE),
    re.compile(r"\byou missed\b", re.IGNORECASE),
    re.compile(r"\byou were supposed to\b", re.IGNORECASE),
    re.compile(r"\bthat'?s not what i asked\b", re.IGNORECASE),
    re.compile(r"\byou skipped\b", re.IGNORECASE),
    re.compile(r"\byou left out\b", re.IGNORECASE),
    re.compile(r"\byou ignored\b", re.IGNORECASE),
]


def detect_frustration(prompt: str) -> bool:
    """Check if prompt contains frustration signals and log if found."""
    for pattern in FRUSTRATION_SIGNALS:
        match = pattern.search(prompt)
        if match:
            _log_frustration(prompt, match.group())
            return True
    return False


def _log_frustration(prompt: str, signal: str):
    """Append frustration event to completion patterns file."""
    try:
        if PATTERNS_FILE.exists():
            patterns = json.loads(PATTERNS_FILE.read_text())
        else:
            patterns = []

        # Truncate prompt for storage (first 200 chars)
        snippet = prompt[:200].strip()

        patterns.append({
            "signal": signal,
            "prompt_snippet": snippet,
            "detected": datetime.now(timezone.utc).isoformat(),
            "resolved": False,
        })

        # Keep last 50 patterns max
        patterns = patterns[-50:]
        PATTERNS_FILE.write_text(json.dumps(patterns, indent=2))
    except Exception:
        pass  # Never fail on logging


def get_overwatch_injection() -> str:
    """Read and consume Overwatch injection file (replaces overwatch-inject.sh)."""
    inject_file = Path.home() / ".claude" / "elara-overwatch-inject.md"
    if inject_file.exists():
        try:
            content = inject_file.read_text().strip()
            inject_file.unlink()
            return content
        except Exception:
            pass
    return ""


def get_corrections(prompt: str) -> list:
    """Find corrections relevant to this prompt."""
    try:
        from daemon.corrections import check_corrections
        matches = check_corrections(prompt, n_results=2)
        return [
            c for c in matches
            if not c.get("_error") and c.get("relevance", 0) > 0.35
        ]
    except Exception:
        return []


def get_workflows(prompt: str) -> list:
    """Find workflow patterns matching this prompt."""
    try:
        from daemon.workflows import check_workflows
        return check_workflows(prompt, n=1)
    except Exception:
        return []


def get_active_goals() -> list:
    """Get active goals (max 3)."""
    try:
        from daemon.goals import list_goals
        return list_goals(status="active")[:3]
    except Exception:
        return []


def get_handoff_items() -> list:
    """Get carry-forward items from last handoff."""
    try:
        from daemon.handoff import load_handoff
        handoff = load_handoff()
        if not handoff:
            return []

        items = []
        for key in ("unfinished", "promises", "reminders"):
            for item in handoff.get(key, [])[:2]:
                text = item.get("text", "").strip()
                if text:
                    items.append(text)
        return items[:3]
    except Exception:
        return []


def get_current_context() -> str:
    """Get current working context (project + episode type)."""
    try:
        ctx_file = Path.home() / ".claude" / "elara-context.json"
        if ctx_file.exists():
            ctx = json.loads(ctx_file.read_text())
            topic = ctx.get("topic", "")
            if topic:
                return topic
    except Exception:
        pass
    return ""


def build_enrichment(prompt: str) -> str:
    """Build the compact enrichment output from all sources."""
    sections = []

    # 1. Context (always if available — sets the frame)
    context = get_current_context()
    if context:
        sections.append(f"[CONTEXT] {context}")

    # 2. Active goals
    goals = get_active_goals()
    if goals:
        names = [g["title"] for g in goals]
        sections.append("[GOALS] " + " | ".join(names))

    # 3. Corrections (self-check — past mistakes to avoid)
    corrections = get_corrections(prompt)
    if corrections:
        lines = []
        for c in corrections[:2]:
            mistake = c.get("mistake", "")[:60]
            fix = c.get("correction", "")[:60]
            lines.append(f"  {mistake} -> {fix}")
        sections.append("[SELF-CHECK]\n" + "\n".join(lines))

    # 4. Matching workflow
    workflows = get_workflows(prompt)
    if workflows:
        wf = workflows[0]
        steps = [s.get("action", "")[:40] for s in wf.get("steps", [])]
        if steps:
            chain = " -> ".join(steps)
            sections.append(f"[WORKFLOW] {wf.get('name', 'unnamed')}: {chain}")

    # 5. Carry-forward from handoff
    items = get_handoff_items()
    if items:
        sections.append("[CARRY-FORWARD] " + " | ".join(items))

    # 6. Overwatch daemon injection (if pending)
    overwatch = get_overwatch_injection()
    if overwatch:
        sections.append(f"[OVERWATCH]\n{overwatch}")

    # 7. Frustration detection (side-effect: logs pattern, adds self-check)
    if detect_frustration(prompt):
        sections.append("[FRUSTRATION DETECTED] Pay extra attention to completion criteria.")

    return "\n".join(sections)


def main():
    """Entry point — read stdin, enrich, output."""
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            sys.exit(0)

        data = json.loads(raw)
        prompt = data.get("prompt", "")

        if not prompt.strip():
            sys.exit(0)

        enrichment = build_enrichment(prompt)

        if enrichment:
            print(enrichment)

    except json.JSONDecodeError:
        pass  # Malformed input — fail silent
    except Exception:
        pass  # Any error — fail silent, never block

    sys.exit(0)


if __name__ == "__main__":
    main()
