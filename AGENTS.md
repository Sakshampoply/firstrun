# AGENTS.md

FirstRun: paste a repo, get a quickstart the agent has actually tested.

This is a one-hour hackathon build with two coding agents working in parallel (Codex and Claude). PLAN.md is the source of truth: read it in full before any change. If PLAN.md and this file disagree, PLAN.md wins.

## Ownership

Do not edit files you don't own. If you need something from the other side, leave a stub with the signature from PLAN.md and add a line under PLAN.md > Decisions.

- Codex owns: firstrun/__main__.py, firstrun/cli.py, firstrun/replay.py, firstrun/ui.py, fixtures/, runs/, README.md, pyproject.toml, .env.example, .gitignore
- Claude owns: firstrun/agent.py, firstrun/tools.py, firstrun/runner.py, firstrun/report.py
- Shared and frozen after Phase 0: firstrun/events.py (written verbatim from PLAN.md). Changing it needs a Decisions line, and old fields stay in place.

## Conventions

- Python 3.12, uv. Deps: anthropic, streamlit, rich. No new deps without a Decisions line.
- No Docker, no threads, no async, no frameworks. Plain functions, dataclasses, generators.
- Small commits, push often. main must always pass: `uv run python -m firstrun --replay runs/sample.jsonl --fast`
- Never commit .env or keys. The only env vars are ANTHROPIC_API_KEY and FIRSTRUN_MODEL.
- Do not ask the human questions mid-phase. Pick the sane default and note it under PLAN.md > Decisions.
- No tests for FirstRun itself. The fixture run is the test.
- Every command the agent reports must have actually run. Never fake evidence, even in sample data: runs/sample.jsonl must look like a real run of fixtures/stale-readme.

## Commands

```
uv sync
uv run python -m firstrun fixtures/stale-readme --record runs/fixture.jsonl
uv run python -m firstrun --replay runs/fixture.jsonl
uv run streamlit run firstrun/ui.py
```

## When a phase ends

Report in at most 5 lines: what works, what is stubbed, what you deviated from and why.
