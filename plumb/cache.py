"""Incremental cache: skip re-verification when nothing relevant changed.

Fingerprint = hash(context file contents) + repo signature (git HEAD, or a
bounded mtime fingerprint for non-git trees). Same inputs -> instant reuse.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import List, Optional

from .model import Claim, Kind, Result, Status

_CACHE_VERSION = 1


def fingerprint(context_files: List[str], repo_signature: str) -> str:
    h = hashlib.sha1()
    h.update(f"v{_CACHE_VERSION}|{repo_signature}|".encode())
    for path in sorted(context_files):
        try:
            data = Path(path).read_bytes()
        except OSError:
            data = b""
        h.update(path.encode())
        h.update(hashlib.sha1(data).digest())
    return h.hexdigest()


def cache_path(root: str) -> Path:
    return Path(root).expanduser().resolve() / ".plumb" / "cache.json"


def load(root: str, fp: str) -> Optional[List[Result]]:
    cp = cache_path(root)
    if not cp.is_file():
        return None
    try:
        blob = json.loads(cp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if blob.get("fingerprint") != fp:
        return None
    results = []
    for r in blob.get("results", []):
        claim = Claim(
            kind=Kind(r["kind"]), raw=r["raw"], line_text=r["line_text"],
            source=r["source"], lineno=r["line"],
        )
        results.append(Result(claim, Status(r["status"]), r.get("evidence", ""), r.get("fix", "")))
    return results


def save(root: str, fp: str, results: List[Result]) -> None:
    cp = cache_path(root)
    try:
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(
            json.dumps({"fingerprint": fp, "results": [r.to_dict() for r in results]}, indent=0),
            encoding="utf-8",
        )
    except OSError:
        pass  # cache is a best-effort optimization; never fail the run over it
