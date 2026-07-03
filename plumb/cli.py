"""Command-line interface: check / gc / budget."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import List

from . import __version__
from . import cache as cache_mod
from . import report as report_mod
from .extract import extract_file
from .ground_truth import RepoIndex
from .model import Result, Status
from .verify import verify_all

# Context files we auto-discover at a target root.
_CONTEXT_NAMES = ("CLAUDE.md", "AGENTS.md", ".clauderc.md")


def _discover_context(root: Path, explicit: List[str], memory_dirs: List[str]) -> List[str]:
    found: List[str] = []
    for name in _CONTEXT_NAMES:
        for candidate in (root / name, root / ".claude" / name):
            if candidate.is_file():
                found.append(str(candidate))
    for path in explicit:
        p = Path(path).expanduser()
        if p.is_file():
            found.append(str(p.resolve()))
    for d in memory_dirs:
        dp = Path(d).expanduser()
        if dp.is_dir():
            found.extend(str(p) for p in sorted(dp.glob("*.md")))
    # Stable de-dup.
    seen, uniq = set(), []
    for f in found:
        if f not in seen:
            seen.add(f)
            uniq.append(f)
    return uniq


def _collect(root: Path, context_files: List[str], use_cache: bool):
    index = RepoIndex(str(root))
    claims = []
    for cf in context_files:
        claims.extend(extract_file(cf))

    fp = cache_mod.fingerprint(context_files, index.signature())
    if use_cache:
        cached = cache_mod.load(str(root), fp)
        if cached is not None:
            return cached, index, True
    results = verify_all(claims, index)
    if use_cache:
        cache_mod.save(str(root), fp, results)
    return results, index, False


def _resolve_target(args) -> Path:
    return Path(args.path).expanduser().resolve()


def cmd_check(args) -> int:
    root = _resolve_target(args)
    context_files = _discover_context(root, args.context, args.memory_dir)
    if not context_files:
        sys.stderr.write(f"plumb: no context files found under {root}\n"
                         f"       (looked for CLAUDE.md / AGENTS.md; pass --context or --memory-dir)\n")
        return 2

    t0 = time.time()
    results, index, hit = _collect(root, context_files, use_cache=not args.no_cache)
    elapsed = time.time() - t0

    if args.json:
        print(report_mod.render_json(results, elapsed, index.files_scanned))
    else:
        print(report_mod.render_tty(results, elapsed, index.files_scanned))
        if hit and not args.no_cache:
            print("\033[2m(results served from cache; use --no-cache to force)\033[0m"
                  if sys.stdout.isatty() else "(results served from cache)")

    stale = sum(1 for r in results if r.status is Status.STALE)
    if args.exit_zero:
        return 0
    return 1 if stale else 0


def cmd_budget(args) -> int:
    root = _resolve_target(args)
    context_files = _discover_context(root, args.context, args.memory_dir)
    if not context_files:
        sys.stderr.write(f"plumb: no context files found under {root}\n")
        return 2
    results, index, _ = _collect(root, context_files, use_cache=not args.no_cache)
    print(report_mod.render_budget(results))
    return 0


def cmd_gc(args) -> int:
    root = _resolve_target(args)
    context_files = _discover_context(root, args.context, args.memory_dir)
    if not context_files:
        sys.stderr.write(f"plumb: no context files found under {root}\n")
        return 2
    results, _, _ = _collect(root, context_files, use_cache=not args.no_cache)
    patch = report_mod.render_gc_patch(results)
    if not patch.strip():
        print("plumb gc: nothing safe to prune (no lines dominated by a stale reference).")
        return 0
    if args.apply:
        _apply_patch(results)
        print("plumb gc: applied — pruned lines dominated by stale references.")
        return 0
    print(patch)
    print("\n# review, then re-run with --apply to prune")
    return 0


def _apply_patch(results: List[Result]) -> None:
    from collections import defaultdict
    drop = defaultdict(set)
    for r in results:
        if r.status is Status.STALE:
            stripped = r.claim.line_text.strip().lstrip("-*# ").strip()
            if stripped.startswith(("[", r.claim.raw)) or len(stripped) <= len(r.claim.raw) + 40:
                drop[r.claim.source].add(r.claim.lineno)
    for src, lines in drop.items():
        try:
            with open(src, "r", encoding="utf-8", errors="replace") as fh:
                original = fh.readlines()
            kept = [ln for i, ln in enumerate(original, start=1) if i not in lines]
            with open(src, "w", encoding="utf-8") as fh:
                fh.writelines(kept)
        except OSError:
            continue


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="plumb", description="Keep your AI's context true to the code.")
    p.add_argument("--version", action="version", version=f"plumb {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    def add_common(sp):
        sp.add_argument("path", nargs="?", default=".", help="repo/target root (default: .)")
        sp.add_argument("--context", action="append", default=[],
                        help="explicit context file (repeatable)")
        sp.add_argument("--memory-dir", action="append", default=[],
                        help="directory of *.md memory files (repeatable)")
        sp.add_argument("--no-cache", action="store_true", help="ignore the incremental cache")

    c = sub.add_parser("check", help="verify context claims against ground truth")
    add_common(c)
    c.add_argument("--json", action="store_true", help="machine-readable output")
    c.add_argument("--exit-zero", action="store_true", help="always exit 0 (don't fail CI)")
    c.set_defaults(func=cmd_check)

    b = sub.add_parser("budget", help="show token cost of context and stale waste")
    add_common(b)
    b.set_defaults(func=cmd_budget)

    g = sub.add_parser("gc", help="propose (or apply) pruning of stale references")
    add_common(g)
    g.add_argument("--apply", action="store_true", help="write the pruning to disk")
    g.set_defaults(func=cmd_gc)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
