"""Verifiers: map each claim to a three-valued Result against ground truth.

Guiding rule: only mark STALE with positive evidence. When in doubt, degrade to
UNVERIFIABLE. A linter that raises false alarms gets uninstalled by day two.
"""
from __future__ import annotations

import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List

from .ground_truth import RepoIndex
from .model import Claim, Kind, Result, Status


def _verify_path(claim: Claim, index: RepoIndex) -> Result:
    raw = claim.raw
    src_dir = Path(claim.source).expanduser().resolve().parent

    if raw.startswith("~") or raw.startswith("/"):
        target = Path(raw).expanduser()
        if target.exists():
            return Result(claim, Status.VERIFIED, f"exists: {target}")
        return Result(claim, Status.STALE, f"no such path: {target}",
                      fix="Remove or update this path — it no longer exists.")

    if raw.startswith("./") or raw.startswith("../"):
        target = (src_dir / raw).resolve()
        if target.exists():
            return Result(claim, Status.VERIFIED, f"exists: {target}")
        alt = (index.root / raw.lstrip("./")).resolve()
        if alt.exists():
            return Result(claim, Status.VERIFIED, f"exists: {alt}")
        return Result(claim, Status.STALE, f"no such path: {target}",
                      fix="Relative path does not resolve from the file or repo root.")

    # Bare filename (e.g. `config.js`): try repo root and the file's directory.
    for base in (index.root, src_dir):
        if (base / raw).exists():
            return Result(claim, Status.VERIFIED, f"exists: {base / raw}")
    return Result(claim, Status.UNVERIFIABLE,
                  "bare filename not found at repo root; may live elsewhere")


def _verify_command(claim: Claim, index: RepoIndex) -> Result:
    # Safety: we only check whether the binary exists. We never execute it —
    # context files are attacker-influenceable input.
    binary = claim.raw.split()[0]
    if shutil.which(binary):
        return Result(claim, Status.VERIFIED, f"binary on PATH: {binary}")
    return Result(claim, Status.UNVERIFIABLE,
                  f"'{binary}' not on PATH here (may be environment-specific)")


def _verify_symbol(claim: Claim, index: RepoIndex) -> Result:
    if not index.indexable:
        return Result(claim, Status.UNVERIFIABLE,
                      "target is not an indexable project (no repo/manifest at root)")
    leaf = claim.raw.split("(")[0].split(".")[-1]
    if index.has_def(leaf):
        return Result(claim, Status.VERIFIED, f"definition found: {leaf}")
    if index.appears_anywhere(leaf):
        return Result(claim, Status.UNVERIFIABLE,
                      f"'{leaf}' referenced but no definition found in index")
    return Result(claim, Status.STALE, f"'{leaf}' not found anywhere in the repo",
                  fix="Symbol appears to be renamed or removed.")


def _verify_dependency(claim: Claim, index: RepoIndex) -> Result:
    present = index.has_dependency(claim.raw)
    if present is None:
        return Result(claim, Status.UNVERIFIABLE, "no dependency manifest found")
    if present:
        return Result(claim, Status.VERIFIED, f"declared in manifest: {claim.raw}")
    return Result(claim, Status.STALE, f"'{claim.raw}' not in any dependency manifest",
                  fix="Dependency may have been dropped.")


def _verify_url(claim: Claim, index: RepoIndex) -> Result:
    return Result(claim, Status.UNVERIFIABLE, "network checks disabled (offline by default)")


_VERIFIERS = {
    Kind.PATH: _verify_path,
    Kind.COMMAND: _verify_command,
    Kind.SYMBOL: _verify_symbol,
    Kind.DEPENDENCY: _verify_dependency,
    Kind.URL: _verify_url,
}


def verify_one(claim: Claim, index: RepoIndex) -> Result:
    return _VERIFIERS[claim.kind](claim, index)


def verify_all(claims: List[Claim], index: RepoIndex, workers: int = 0) -> List[Result]:
    if not claims:
        return []
    if workers <= 0:
        workers = min(32, (os.cpu_count() or 4) * 4)
    # I/O-bound (stat / which / file reads) -> threads dodge the GIL fine.
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda c: verify_one(c, index), claims))
