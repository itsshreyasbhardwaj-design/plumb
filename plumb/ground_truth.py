"""Ground-truth adapters: the repository as it actually is right now.

The symbol index is built lazily and only when symbol/dependency claims exist,
so linting a context file full of paths never walks the tree at all.
"""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Dict, List, Optional, Set

_IGNORE_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "venv", ".venv", "env", ".env",
    "__pycache__", ".mypy_cache", ".pytest_cache", "dist", "build", "target",
    ".next", ".nuxt", "out", "coverage", ".tox", "vendor", ".idea", ".plumb",
}
_CODE_EXT = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".rb", ".java", ".kt",
    ".c", ".h", ".cc", ".cpp", ".hpp", ".cs", ".php", ".swift", ".scala",
}

# Generic "definition-like" patterns across common languages.
_DEF_PATTERNS = [
    re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)"),                 # python
    re.compile(r"^\s*class\s+([A-Za-z_]\w*)"),                            # py/js/java/...
    re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_]\w*)"),  # js/ts
    re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_]\w*)\s*="),  # js/ts
    re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)"),            # go
    re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z_]\w*)"),       # rust
    re.compile(r"^\s*(?:type|struct|enum|trait|interface|module)\s+([A-Za-z_]\w*)"),
    re.compile(r"^\s*(?:def|module)\s+([A-Za-z_]\w*)"),                   # ruby
]
_WORD = re.compile(r"[A-Za-z_]\w{2,}")
_MAX_IDENTS = 300_000


class RepoIndex:
    _MANIFEST_NAMES = (
        ".git", "package.json", "pyproject.toml", "requirements.txt",
        "go.mod", "Cargo.toml", "setup.py", "pom.xml", "build.gradle",
    )

    def __init__(self, root: str, max_files: int = 20000, max_file_bytes: int = 1_000_000):
        self.root = Path(root).expanduser().resolve()
        self.max_files = max_files
        self.max_file_bytes = max_file_bytes
        self.defs: Set[str] = set()
        self.idents: Set[str] = set()   # every identifier seen, for O(1) lookup
        self.idents_truncated = False
        self.deps: Set[str] = set()
        self.files: List[Path] = []
        self.files_scanned = 0
        self.truncated = False
        self.has_manifest = False
        self._built = False
        self._lock = threading.Lock()
        # Only treat the root as an indexable project if it carries a marker.
        # This stops us from ever walking a home directory or the filesystem.
        self.indexable = any((self.root / n).exists() for n in self._MANIFEST_NAMES)

    # -- lazy build ---------------------------------------------------------
    def ensure_built(self) -> None:
        # Double-checked locking: the build must complete before any concurrent
        # verifier thread is allowed to read defs/deps/files, so _built flips to
        # True only after the work is done.
        if self._built:
            return
        with self._lock:
            if self._built:
                return
            if self.indexable:
                self._parse_manifests()
                self._walk_and_index()
            self._built = True

    def _walk_and_index(self) -> None:
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in _IGNORE_DIRS and not d.startswith(".")]
            for name in filenames:
                if self.files_scanned >= self.max_files:
                    self.truncated = True
                    return
                p = Path(dirpath) / name
                if p.suffix.lower() not in _CODE_EXT:
                    continue
                try:
                    if p.stat().st_size > self.max_file_bytes:
                        continue
                    text = p.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                self.files.append(p)
                self.files_scanned += 1
                for line in text.splitlines():
                    for pat in _DEF_PATTERNS:
                        m = pat.match(line)
                        if m:
                            self.defs.add(m.group(1))
                if not self.idents_truncated:
                    self.idents.update(_WORD.findall(text))
                    if len(self.idents) > _MAX_IDENTS:
                        self.idents_truncated = True  # fall back to file scan

    def _parse_manifests(self) -> None:
        pj = self.root / "package.json"
        if pj.is_file():
            try:
                data = json.loads(pj.read_text(encoding="utf-8", errors="ignore"))
                for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
                    self.deps.update((data.get(key) or {}).keys())
                self.has_manifest = True
            except (OSError, ValueError):
                pass
        req = self.root / "requirements.txt"
        if req.is_file():
            try:
                for line in req.read_text(encoding="utf-8", errors="ignore").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        name = re.split(r"[<>=!~\[; ]", line, 1)[0].strip()
                        if name:
                            self.deps.add(name)
                self.has_manifest = True
            except OSError:
                pass
        for manifest, pat in (
            (self.root / "go.mod", re.compile(r"^\s*([\w.\-/]+)\s+v\d")),
            (self.root / "Cargo.toml", re.compile(r'^\s*([A-Za-z0-9_\-]+)\s*=')),
            (self.root / "pyproject.toml", re.compile(r'["\']([A-Za-z0-9_.\-]+)\s*(?:[<>=!~]|["\'])')),
        ):
            if manifest.is_file():
                try:
                    for line in manifest.read_text(encoding="utf-8", errors="ignore").splitlines():
                        m = pat.match(line) if manifest.name != "pyproject.toml" else pat.search(line)
                        if m:
                            self.deps.add(m.group(1))
                    self.has_manifest = True
                except OSError:
                    pass

    # -- signature (for the incremental cache) ------------------------------
    def signature(self) -> str:
        import hashlib
        head = _git_head(self.root)
        if head:
            return f"git:{head}"
        # Non-git tree: cheap, non-recursive fingerprint of the top level only.
        # Never walk the whole tree here — that could be a home directory.
        h = hashlib.sha1()
        try:
            entries = [e for e in os.scandir(self.root) if e.name != ".plumb"]
            for entry in sorted(entries, key=lambda e: e.name)[:500]:
                try:
                    st = entry.stat()
                    h.update(f"{entry.name}:{int(st.st_mtime)}:{st.st_size}".encode())
                except OSError:
                    continue
        except OSError:
            pass
        return "fs:" + h.hexdigest()[:16]

    # -- lookups ------------------------------------------------------------
    def has_def(self, name: str) -> bool:
        self.ensure_built()
        return name in self.defs

    def appears_anywhere(self, name: str) -> bool:
        self.ensure_built()
        if not self.idents_truncated:
            return name in self.idents  # O(1); no disk re-read
        for p in self.files:  # fallback for very large repos
            try:
                if name in p.read_text(encoding="utf-8", errors="ignore"):
                    return True
            except OSError:
                continue
        return False

    def has_dependency(self, name: str) -> Optional[bool]:
        self.ensure_built()
        if not self.has_manifest:
            return None
        low = {d.lower() for d in self.deps}
        return name.lower() in low


def _git_head(root: Path) -> Optional[str]:
    import subprocess
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return None
