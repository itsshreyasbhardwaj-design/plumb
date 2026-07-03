"""Deterministic claim extraction.

No LLM, no network, no guessing. We pull out only the spans we can classify
into a checkable kind (path / command / symbol / dependency / url). Prose we
cannot classify is left alone rather than emitted as noise.
"""
from __future__ import annotations

import re
from typing import List, Optional

from .model import Claim, Kind

_BACKTICK = re.compile(r"`([^`]+)`")
_URL = re.compile(r"https?://[^\s`)\]<>]+")
# Home/absolute/explicit-relative paths, no embedded spaces. The lookbehind
# stops us matching inside words like "TCP/IP" or "and/or".
_PATH_TOKEN = re.compile(r"(?<![\w.])(~/[\w.\-/]+|\.{1,2}/[\w.\-/]+|/[\w.\-/]{2,})")
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*(?:\(\))?$")
_FILENAME_EXT = re.compile(
    r"^[\w.\-]+\.(?:js|ts|tsx|jsx|py|go|rs|rb|java|kt|json|toml|ya?ml|md|txt|sh|cfg|ini|env)$"
)

_COMMAND_BINS = {
    "npm", "npx", "pnpm", "yarn", "bun", "deno", "node",
    "python", "python3", "pip", "pip3", "uv", "uvx", "poetry", "pytest", "ruff",
    "cargo", "rustc", "go", "make", "cmake", "gradle", "mvn",
    "git", "docker", "kubectl", "terraform", "ffmpeg", "ffprobe", "brew", "curl", "wget",
}

_DEP_TRIGGER = re.compile(r"\b(use|uses|using|depend|dependency|library|package|framework)\b", re.I)

# Real absolute paths almost always have >=2 segments or a known root. A lone
# "/word" is far more likely a slash-command (e.g. /impeccable, /tdd) than a
# file, so we refuse to treat it as a path and never flag it stale.
_KNOWN_ROOTS = {
    "tmp", "etc", "var", "opt", "usr", "sbin", "bin", "root", "home", "users",
    "applications", "library", "system", "private", "volumes", "dev", "srv",
    "mnt", "media", "proc",
}


def _is_path_token(tok: str) -> bool:
    if " " in tok:
        return False
    if tok.startswith(("~/", "./", "../")):
        return True
    if tok.startswith("/"):
        # Filesystem absolute paths begin with a real mount root. This rejects
        # API routes (/api/auth/verify-otp) and web asset paths (/photos/x.jpg),
        # which look absolute but are not files.
        segs = [s for s in tok.strip("/").split("/") if s]
        return bool(segs) and segs[0].lower() in _KNOWN_ROOTS
    return False


def _classify_backtick(tok: str) -> Optional[Kind]:
    tok = tok.strip()
    if not tok:
        return None
    if tok.startswith("http://") or tok.startswith("https://"):
        return Kind.URL
    if _is_path_token(tok):
        return Kind.PATH
    if _FILENAME_EXT.match(tok):
        return Kind.PATH
    first = tok.split()[0]
    if first in _COMMAND_BINS:
        return Kind.COMMAND
    if " " not in tok and _IDENT.match(tok) and not tok.isupper():
        # Skip trivially short or ALL-CAPS tokens (usually acronyms/env vars).
        if len(tok.rstrip("()")) >= 3:
            return Kind.SYMBOL
    return None


def extract_file(path: str) -> List[Claim]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return []

    claims: List[Claim] = []
    seen = set()

    def emit(kind: Kind, raw: str, line_text: str, lineno: int) -> None:
        key = (kind, raw, lineno)
        if key in seen:
            return
        seen.add(key)
        claims.append(Claim(kind=kind, raw=raw, line_text=line_text, source=path, lineno=lineno))

    for i, line in enumerate(lines, start=1):
        dep_ctx = bool(_DEP_TRIGGER.search(line))
        for m in _BACKTICK.finditer(line):
            tok = m.group(1).strip()
            kind = _classify_backtick(tok)
            if kind is None:
                continue
            if kind is Kind.SYMBOL and dep_ctx:
                kind = Kind.DEPENDENCY
            emit(kind, tok, line, i)

        # Prose remainder: strip backticked spans, then harvest bare URLs/paths.
        remainder = _BACKTICK.sub(" ", line)
        for m in _URL.finditer(remainder):
            emit(Kind.URL, m.group(0).rstrip(".,);"), line, i)
        remainder = _URL.sub(" ", remainder)
        for m in _PATH_TOKEN.finditer(remainder):
            tok = m.group(0).rstrip(".,);")
            if _is_path_token(tok):
                emit(Kind.PATH, tok, line, i)

    return claims
