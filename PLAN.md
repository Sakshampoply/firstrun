# FirstRun: plan and source of truth

Pitch: paste a repo, get a quickstart the agent has actually tested.

Success for the hour: one repo, one observed setup failure, one successful recovery, one evidence-backed QUICKSTART.md, shown live from the UI (from the CLI if the UI breaks).

Two coding agents build this in parallel: Codex and Claude. Both read this file before writing code. Ownership is in AGENTS.md. If you need an interface change, add a line under Decisions and leave a stub; never silently change a file you don't own.

## Scope

In: public GitHub URL or local path; small pure-Python repos; one install path (pyproject or requirements.txt) into a uv venv; verification via pytest or a smoke command from the README; Streamlit UI; CLI; record and replay.

Out, do not build: Docker, private repos, databases or services, non-Python stacks, auth, deployment, opening PRs, multiple agents, persistence, tests for FirstRun itself, config files, logging frameworks.

## Layout and ownership

```
firstrun/
  __init__.py
  __main__.py      # calls cli.main()                              Codex
  cli.py           # python -m firstrun <target> [--record] [--replay] [--fast]   Codex
  replay.py        # paces recorded events                         Codex
  ui.py            # Streamlit app                                 Codex
  events.py        # Event dataclass + jsonl helpers   SHARED, frozen after Phase 0
  agent.py         # run(target) -> Iterator[Event], Claude tool loop   Claude
  tools.py         # tool schemas + implementations                Claude
  runner.py        # workspace + sandbox-lite command execution    Claude
  report.py        # report validation + QUICKSTART.md rendering   Claude
fixtures/stale-readme/   # demo repo with stale README instructions   Codex
runs/              # recorded runs (jsonl), sample.jsonl is hand-written   Codex
out/               # QUICKSTART.md written here, gitignored
PLAN.md  AGENTS.md  README.md  pyproject.toml  .env.example  .gitignore
```

Deps: anthropic, streamlit, rich. Python 3.12, uv. Nothing else without a Decisions line.

Env: ANTHROPIC_API_KEY (required), FIRSTRUN_MODEL (default claude-sonnet-5-5).

## Shared contract: firstrun/events.py

Codex writes this file exactly as below in Phase 0. After that it is frozen.

```python
from __future__ import annotations
import json
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Iterable, Iterator

EVENT_TYPES = (
    "status",            # msg: one progress line for the feed
    "tool_call",         # data: {name, input}
    "tool_result",       # data: {name, ok, summary}
    "command_started",   # data: {cmd}
    "command_finished",  # data: {cmd, exit_code, duration_s, stdout_tail, stderr_tail}
    "recovery",          # data: {failed_cmd, hypothesis, next_cmd, attempt}
    "report_ready",      # data: {report, quickstart_md}
    "blocked",           # data: {reason, report, quickstart_md}   report may be partial
    "error",             # data: {message}
)


@dataclass
class Event:
    type: str
    msg: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)  # epoch seconds

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, line: str) -> "Event":
        return cls(**json.loads(line))


def write_jsonl(path: str, events: Iterable[Event]) -> Iterator[Event]:
    """Tee: writes each event to path as it passes through, yields it unchanged."""
    with open(path, "w", encoding="utf-8") as f:
        for ev in events:
            f.write(ev.to_json() + "\n")
            f.flush()
            yield ev


def read_jsonl(path: str) -> list[Event]:
    with open(path, encoding="utf-8") as f:
        return [Event.from_json(line) for line in f if line.strip()]
```

Rules:
- A run always ends with exactly one terminal event: report_ready, blocked, or error.
- The UI and CLI consume Event objects only. They never import agent internals beyond `from firstrun.agent import run`.
- `ts` is epoch seconds; replay paces by deltas.

## Shared contract: run()

```python
# firstrun/agent.py
def run(target: str) -> Iterator[Event]: ...
```

`target` is a GitHub URL (https://github.com/owner/repo) or a local directory path. The function is a generator; it yields events as they happen and returns after the terminal event. Phase 0 stub:

```python
def run(target: str) -> Iterator[Event]:
    yield Event("status", f"agent stub: {target}")
    yield Event("blocked", "agent not implemented", {"reason": "stub", "report": {}, "quickstart_md": ""})
```

## Shared contract: report dict

Produced by report.py, carried inside report_ready and blocked events as `data["report"]`, plus the rendered markdown in `data["quickstart_md"]`.

```json
{
  "target": "fixtures/stale-readme",
  "name": "pingpong",
  "summary": "Two or three sentences on what the project does.",
  "read_first": [{"path": "src/pingpong/app.py", "why": "entrypoint"}],
  "setup_steps": [
    {"cmd": "uv pip install -r requirements.txt", "status": "failed", "note": "file does not exist"},
    {"cmd": "uv pip install -e \".[dev]\"", "status": "passed", "note": "installs from pyproject"}
  ],
  "verification": {"cmd": "pytest -q", "status": "passed", "evidence": "1 passed in 0.02s"},
  "obstacles": [
    {"what": "README install command points at a missing requirements.txt",
     "workaround": "install from pyproject with uv", "resolved": true}
  ],
  "elapsed_s": 73.4,
  "tool_calls": 9
}
```

`status` is one of: passed, failed, untested. Nothing else. `read_first` has at most 5 entries.

QUICKSTART.md rendering (report.py):

```
# pingpong: quickstart (verified by FirstRun, 2026-10-11)

What it is: ...

## Setup
1. [passed] uv venv && source .venv/bin/activate
2. [failed] uv pip install -r requirements.txt   (file does not exist)
3. [passed] uv pip install -e ".[dev]"

## Verify
[passed] pytest -q  ->  1 passed in 0.02s

## Gotchas
- README says `pip install -r requirements.txt`; that file does not exist. Install from pyproject.

## Read first
- src/pingpong/app.py: entrypoint
```

## Agent (Claude)

Single Claude agent, Messages API tool-use loop, no framework. Model from FIRSTRUN_MODEL, default claude-sonnet-5-5.

Tools (JSON schemas in tools.py):
- list_files(max_depth=3, max_entries=200): tree of the repo, skips .git, .venv, node_modules, __pycache__
- read_file(path, max_bytes=6000)
- search(pattern, glob="**/*.py"): up to 30 matches as path:line:text
- run_command(cmd): returns {exit_code, duration_s, stdout_tail, stderr_tail}; emits command_started and command_finished
- write_report(report): validates against the report dict, renders quickstart_md, emits report_ready, ends the loop

Budgets (constants in agent.py): max_tool_calls=14, max_recoveries=2 per failing step, cmd_timeout_s=90, total_budget_s=300. Hitting any budget forces a blocked event carrying whatever partial report exists.

Loop shape: inspect (README, pyproject or requirements, tests dir) -> attempt setup -> on failure read the error, state a hypothesis (emit recovery), try one corrected command -> verify (pytest if tests exist, else the smallest smoke command from the README) -> write_report.

System prompt rules (gist):
- Every command listed in the report must have been executed through run_command in this run; anything else is marked untested.
- Use `uv pip install` instead of `pip install`; the venv is already active.
- Never invent output. Evidence is the tail of real stdout/stderr.
- Prefer the smallest verification that proves the project runs.
- Call write_report as soon as verification passes, or when told the budget is exhausted.

## Runner (Claude): sandbox-lite

- Workspace: temp dir. URL -> `git clone --depth 1`; local path -> copytree (skip .git, .venv).
- `uv venv .venv` created once per run. Commands run with cwd=repo, shell=True, timeout=cmd_timeout_s, env = system PATH with .venv/bin first, VIRTUAL_ENV set, any env var matching KEY|TOKEN|SECRET|PASSWORD removed. ANTHROPIC_API_KEY is never passed to commands.
- Denylist (regex checked before running; rejected commands return exit_code 126 and are reported as failed): sudo, rm -rf, curl or wget piped to a shell, chmod, chown, docker, git push, absolute paths or ~ or .. that leave the repo.
- Output tails capped at 3000 chars each.
- This is not a security boundary. Demo targets are pre-vetted: the fixture plus at most two small public repos tried during Phase 3.

## CLI and UI (Codex)

CLI: `uv run python -m firstrun <target> [--record runs/x.jsonl] [--replay runs/x.jsonl] [--fast]`
- Prints the feed with rich: status dim, commands bold, recovery highlighted, terminal report as a markdown panel.
- Writes out/QUICKSTART.md from `quickstart_md` on report_ready or blocked and prints the path.
- --record tees through events.write_jsonl. --replay reads runs/x.jsonl and paces by ts deltas, each gap capped at 1.5 s; --fast removes pacing. Replay prints a REPLAY banner.

Streamlit: `uv run streamlit run firstrun/ui.py`
- Inputs: target text box, Run button, a "Replay a recorded run" selector listing runs/*.jsonl, labelled REPLAY on screen.
- Activity feed: one line per event, appended as the generator yields (plain container writes inside the for loop; no threads, no polling).
- Report panel on report_ready or blocked: summary, setup steps table with status, verification evidence, obstacles, read-first list, st.download_button for QUICKSTART.md. Blocked shows a warning banner with the reason.
- The UI consumes event dicts only.

## Demo fixture (Codex): fixtures/stale-readme

Tiny package "pingpong" whose README is stale in exactly two places.

```
fixtures/stale-readme/
  README.md               # says: pip install -r requirements.txt ; python -m pingpong.server ; pytest
  pyproject.toml          # name pingpong, src layout, setuptools backend,
                          # [project.optional-dependencies] dev = ["pytest"], pytest testpaths = ["tests"]
  src/pingpong/__init__.py   # def ping() -> str: return "pong"
  src/pingpong/app.py        # main() prints ping(); if __name__ == "__main__": main()
  tests/test_pingpong.py     # assert ping() == "pong"
```

Stale items: requirements.txt does not exist (project uses pyproject); the module is pingpong.app, not pingpong.server. Expected agent path: install fails -> recovery to `uv pip install -e ".[dev]"` -> `pytest -q` passes -> report with one resolved obstacle (the second stale item is a bonus if the agent notices it).

Pre-warm the uv cache in Phase 1 by running the fixture once while WiFi works, so the live demo needs no network.

## Phases (minutes from repo creation; demoable at 40)

| Phase | Owner | Work | Done when |
|---|---|---|---|
| P0 0-8 | Codex | pyproject, package, events.py verbatim, cli + replay, ui.py on sample events, fixture, runs/sample.jsonl hand-written, stubs for the four Claude files with final signatures, push | `uv run python -m firstrun --replay runs/sample.jsonl --fast` prints feed + report; Streamlit replays the sample; repo URL shared |
| P0 0-8 | Claude | agent.py, tools.py, runner.py, report.py written against this doc, in parallel | files ready to drop in |
| P1 8-25 | Claude | live run on fixtures/stale-readme completes with report_ready; record runs/fixture.jsonl | `uv run python -m firstrun fixtures/stale-readme --record runs/fixture.jsonl` ends in report_ready |
| P1 8-25 | Codex | UI wired to live run(), report panel, download, replay selector, README | UI replays runs/sample.jsonl end to end |
| P2 25-40 | Both | integrate on main, run the fixture live from the UI, fix the single biggest break | live fixture run from UI shows failure, recovery, green pytest, report. DEMOABLE |
| P3 40-50 | Codex | record the good run as runs/fixture.jsonl, rehearse replay | replay looks identical to live |
| P3 40-50 | Claude | try one pre-vetted tiny public Python repo via URL; if it fails, do not fix it | fixture stays the hero demo |
| P4 50-60 | Parth | two rehearsals, decide live vs replay per step, pitch | |

Kill rules:
- Minute 30, agent not finishing on the fixture: drop the recovery loop, hardcode the plan (read README, run its commands, verify, report), keep the evidence. Verification is the demo, not autonomy.
- Minute 45, UI flaky: demo from the CLI. The rich output is enough.
- Never cut verification to save time; cut repo breadth instead.

## Demo script (2 minutes)

1. "FirstRun tries a repo's setup instructions and hands the next developer a quickstart backed by real runs."
2. Paste fixtures/stale-readme, hit Run. The README install step fails on a missing requirements.txt. The agent reads the error, finds pyproject, installs with uv, pytest goes green.
3. Report: steps marked passed or failed, the gotcha spelled out, download QUICKSTART.md.
4. If WiFi or the API is down: run the replay, with the REPLAY label visible. Say it is a replay.

## Decisions

- D1 No Docker. Sandbox-lite (temp dir, uv venv, denylist, timeouts) on pre-vetted targets. Docker would eat the hour.
- D2 CLI first; Streamlit is a thin consumer of run(). If the UI breaks, the CLI is the demo.
- D3 Local paths are first-class targets. The hero demo runs on the local fixture so WiFi cannot kill it. URL support is for the stretch demo.
- D4 One Claude agent, claude-sonnet-5-5, raw Messages API tool loop, no framework.
- D5 events.py is frozen after Phase 0.
- D6 Python only, one install path, no services.
- D7 Replay is always labelled REPLAY on screen and in the pitch.
- D8 Report statuses are passed, failed, untested. No other words.
- D9 FIRSTRUN_MODEL env var swaps the model; nothing else is configurable.

- D10 Phase 0 lives in outputs/FirstRun, a self-contained deliverable repository.
- D11 Only agent.run has a frozen function signature; tools.py, runner.py and report.py remain module placeholders for Claude to define.
- D12 sample.jsonl is labelled illustrative, assembled from actual fixture command checks with synthetic event timing; it is not an autonomous agent recording.
- D13 Live runs need API connectivity even with a local fixture and prewarmed package cache. Replay works offline.
- D14 CLI exit codes: 0 report_ready, 2 blocked, 1 error, 130 interrupted. --record without a path chooses a timestamped filename.
- D15 .python-version pins Python 3.12; setuptools is a build dependency, not a new runtime dependency. uv.lock is committed for reproducibility.
- D16 Model name retained from supplied plan, not verified in Phase 0; Claude must confirm FIRSTRUN_MODEL against account availability before live integration.
- D17 User authorized GitHub repository creation and v0 publication on 2026-10-11. Publish the tracked Phase 0 source publicly as Sakshampoply/firstrun; credentials, virtual environments and generated output remain excluded.
