"""Core data types shared across the pipeline."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum


class Kind(str, Enum):
    PATH = "path"
    COMMAND = "command"
    SYMBOL = "symbol"
    DEPENDENCY = "dependency"
    URL = "url"


class Status(str, Enum):
    VERIFIED = "verified"          # ground truth confirms the claim
    UNVERIFIABLE = "unverifiable"  # can't prove or disprove -> ask a human
    STALE = "stale"               # ground truth contradicts the claim


# Only these kinds are ever marked STALE. Everything else degrades to
# UNVERIFIABLE when unconfirmed, so the linter never cries wolf.
DEFINITIVE = {Kind.PATH, Kind.DEPENDENCY, Kind.SYMBOL}


@dataclass(frozen=True)
class Claim:
    kind: Kind
    raw: str          # the asserted token, e.g. "~/OpenMontage" or "getUser"
    line_text: str    # the full source line, for context in the report
    source: str       # context file the claim came from
    lineno: int       # 1-based line number

    @property
    def id(self) -> str:
        seed = f"{self.source}:{self.lineno}:{self.kind.value}:{self.raw}"
        return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]


@dataclass
class Result:
    claim: Claim
    status: Status
    evidence: str = ""
    fix: str = ""

    def to_dict(self) -> dict:
        c = self.claim
        return {
            "id": c.id,
            "kind": c.kind.value,
            "raw": c.raw,
            "status": self.status.value,
            "evidence": self.evidence,
            "fix": self.fix,
            "source": c.source,
            "line": c.lineno,
            "line_text": c.line_text.strip(),
        }
