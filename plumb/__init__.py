"""Plumb — keep your AI's context true to the code.

A zero-dependency context-integrity linter. It treats CLAUDE.md, AGENTS.md and
memory files as *assertions about the repository* and verifies each one against
ground truth, so stale instructions become a caught error instead of a silent
tax on every session.
"""

__version__ = "0.1.0"
