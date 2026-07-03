# Plumb

**Keep your AI's context true to the code.**

Every memory tool and every `CLAUDE.md` is append-heavy and never garbage-collected. Over months, they fill with paths that were deleted, functions that were renamed, and conventions that were abandoned. Stale context is worse than no context — it steers the agent wrong *and* burns context budget on every session.

Plumb treats your `CLAUDE.md`, `AGENTS.md`, and memory files as **assertions about the repository** and verifies each one against ground truth.

```
$ plumb check .
XX STALE (3)
  XX path    ~/OpenMontage            CLAUDE.md:154  no such path: /Users/you/OpenMontage
  XX symbol  handleRetry              CLAUDE.md:88   not found anywhere in the repo
  XX dep     flask                    CLAUDE.md:11   not in any dependency manifest
...
34 claims  27 verified  4 unverifiable  3 stale
~3533 tokens wasted on stale context · 12 ms
```

## Why it's different

The Claude Code ecosystem is full of tools that **write** context (claude-mem, memory MCPs) and **record** provenance (git blame for AI). Plumb is the missing **validation / garbage-collection** layer — the janitor for the memory landfill those tools create. It complements them; it replaces none.

## Install

```
pipx install plumb-context      # or: python3 -m plumb  (zero dependencies)
```

Requires only Python 3.8+. No API key, no network, nothing leaves your machine.

## Commands

| Command | What it does |
|---|---|
| `plumb check <repo>` | Verify context claims; exit 1 if any are stale (CI-friendly) |
| `plumb budget <repo>` | Per-file token cost of context and how much is wasted on stale claims |
| `plumb gc <repo>` | Propose a safe prune patch (`--apply` to write) |

Point at extra sources with `--context FILE` and `--memory-dir DIR`.

## The three-valued model

Plumb never cries wolf. Every claim is one of:

- **verified** — ground truth confirms it
- **unverifiable** — can't prove or disprove; left for a human
- **stale** — ground truth *contradicts* it (positive evidence required)

A claim is only ever marked **stale** with proof (a path that resolves nowhere, a symbol defined nowhere, a dependency in no manifest). Anything ambiguous degrades to *unverifiable*.

## How it works

1. **Extract** — deterministic, no LLM. Pulls typed claims (path / command / symbol / dependency / url) from context files. Slash-commands, API routes, and prose are not mistaken for paths.
2. **Ground truth** — a lazily-built, project-gated index (tree walk + manifest parse). Never walks a home directory or non-project root.
3. **Verify** — parallel, three-valued, with evidence and a suggested fix.

## Performance

- **Incremental cache** keyed by git HEAD (or a cheap mtime fingerprint) — unchanged inputs return instantly.
- **Parallel verification** across claims (I/O-bound, threaded).
- **Single-pass index** with an O(1) identifier set; no per-symbol disk re-reads.
- **Bounded & gated** — ignores `node_modules`/`.git`/build dirs, caps file size and count, and only indexes real project roots.

## Known limitations (v0.1)

- Paths containing spaces are truncated at the first space.
- Prose claims ("we prefer X over Y") and intent-sensitive mentions (e.g. a deny-list of paths that *shouldn't* exist) are reported as *unverifiable*, not auto-checked. Semantic claim classification is roadmapped behind an optional local model.

## License

MIT
