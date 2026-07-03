"""Rendering: human report, JSON, token budget, and a safe GC patch."""
from __future__ import annotations

import difflib
import json
import os
import sys
from collections import defaultdict
from typing import Dict, List

from .model import Result, Status

_ICON = {Status.VERIFIED: "OK ", Status.UNVERIFIABLE: "?? ", Status.STALE: "XX "}
_COLOR = {Status.VERIFIED: "\033[32m", Status.UNVERIFIABLE: "\033[33m", Status.STALE: "\033[31m"}
_RESET = "\033[0m"
_DIM = "\033[2m"
_BOLD = "\033[1m"


def _use_color() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _c(text: str, code: str) -> str:
    return f"{code}{text}{_RESET}" if _use_color() else text


def est_tokens(text: str) -> int:
    return max(1, round(len(text) / 4))


def summary_counts(results: List[Result]) -> Dict[Status, int]:
    counts = {s: 0 for s in Status}
    for r in results:
        counts[r.status] += 1
    return counts


def render_tty(results: List[Result], elapsed: float, files_scanned: int) -> str:
    out: List[str] = []
    by_status: Dict[Status, List[Result]] = defaultdict(list)
    for r in results:
        by_status[r.status].append(r)

    for status in (Status.STALE, Status.UNVERIFIABLE, Status.VERIFIED):
        group = by_status.get(status, [])
        if not group:
            continue
        header = f"{_ICON[status]}{status.value.upper()} ({len(group)})"
        out.append(_c(header, _BOLD + _COLOR[status]))
        for r in sorted(group, key=lambda x: (x.claim.source, x.claim.lineno)):
            c = r.claim
            loc = f"{os.path.basename(c.source)}:{c.lineno}"
            out.append(f"  {_c(_ICON[status].strip(), _COLOR[status])} "
                       f"{c.kind.value:<10} {c.raw}")
            out.append(_c(f"       {loc}  {r.evidence}", _DIM))
            if r.fix and status is Status.STALE:
                out.append(_c(f"       fix: {r.fix}", _DIM))
        out.append("")

    counts = summary_counts(results)
    total = len(results)
    wasted = sum(est_tokens(r.claim.line_text) for r in results if r.status is Status.STALE)
    line = (f"{total} claims  "
            f"{_c(str(counts[Status.VERIFIED]) + ' verified', _COLOR[Status.VERIFIED])}  "
            f"{_c(str(counts[Status.UNVERIFIABLE]) + ' unverifiable', _COLOR[Status.UNVERIFIABLE])}  "
            f"{_c(str(counts[Status.STALE]) + ' stale', _COLOR[Status.STALE])}")
    out.append(_c("─" * 60, _DIM))
    out.append(line)
    out.append(_c(f"~{wasted} tokens wasted on stale context  ·  "
                  f"{files_scanned} code files indexed  ·  {elapsed*1000:.0f} ms", _DIM))
    return "\n".join(out)


def render_json(results: List[Result], elapsed: float, files_scanned: int) -> str:
    counts = summary_counts(results)
    payload = {
        "summary": {
            "total": len(results),
            "verified": counts[Status.VERIFIED],
            "unverifiable": counts[Status.UNVERIFIABLE],
            "stale": counts[Status.STALE],
            "wasted_tokens": sum(est_tokens(r.claim.line_text)
                                 for r in results if r.status is Status.STALE),
            "files_indexed": files_scanned,
            "elapsed_ms": round(elapsed * 1000, 1),
        },
        "results": [r.to_dict() for r in results],
    }
    return json.dumps(payload, indent=2)


def render_budget(results: List[Result]) -> str:
    per_file: Dict[str, Dict[str, int]] = defaultdict(lambda: {"claims": 0, "stale": 0, "wasted": 0})
    for r in results:
        f = per_file[r.claim.source]
        f["claims"] += 1
        if r.status is Status.STALE:
            f["stale"] += 1
            f["wasted"] += est_tokens(r.claim.line_text)
    out = [_c(f"{'context file':<44}{'claims':>8}{'stale':>7}{'~wasted':>9}", _BOLD)]
    out.append(_c("─" * 68, _DIM))
    for src, d in sorted(per_file.items()):
        name = src if len(src) <= 42 else "…" + src[-41:]
        out.append(f"{name:<44}{d['claims']:>8}{d['stale']:>7}{d['wasted']:>9}")
    return "\n".join(out)


def render_gc_patch(results: List[Result]) -> str:
    """Propose removing lines whose whole purpose is a now-stale reference.

    Conservative: only lines that are a bullet/reference dominated by a single
    stale claim are proposed for deletion. Everything else is left for a human.
    """
    stale_by_file: Dict[str, List[Result]] = defaultdict(list)
    for r in results:
        if r.status is Status.STALE:
            stale_by_file[r.claim.source].append(r)

    patches: List[str] = []
    for src, group in sorted(stale_by_file.items()):
        try:
            with open(src, "r", encoding="utf-8", errors="replace") as fh:
                original = fh.read().splitlines(keepends=True)
        except OSError:
            continue
        drop_lines = set()
        for r in group:
            stripped = r.claim.line_text.strip().lstrip("-*# ").strip()
            # Heuristic: line is "mostly" this reference (short, single claim).
            if stripped.startswith(("[", r.claim.raw)) or len(stripped) <= len(r.claim.raw) + 40:
                drop_lines.add(r.claim.lineno)
        if not drop_lines:
            continue
        modified = [ln for i, ln in enumerate(original, start=1) if i not in drop_lines]
        diff = difflib.unified_diff(original, modified, fromfile=src, tofile=src + " (gc)")
        patches.append("".join(diff))
    return "\n".join(p for p in patches if p.strip())
