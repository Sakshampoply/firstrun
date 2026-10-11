# FirstRun

Paste a repo, get a quickstart the agent has actually tested.

**Phase 0:** CLI, Streamlit UI, replay and fixture work. The four Claude-owned modules are placeholders; live runs intentionally finish `blocked` until those modules arrive. The sample is an **illustrative replay**, assembled from real fixture command checks, not a recorded autonomous run.

## Start here — three commands

Run from this repository's directory. Install [uv](https://docs.astral.sh/uv/) first if needed. Python 3.12 and dependencies are installed by uv.

```sh
uv sync
uv run python -m firstrun --replay runs/sample.jsonl --fast
uv run streamlit run firstrun/ui.py
```

In the UI select **REPLAY**, choose `sample.jsonl`, check **Fast replay**, then click **Run**. Read the activity and report; click **Download QUICKSTART.md**.

## Live integration

Give Claude `PLAN.md`, `AGENTS.md`, and this repository. Replace only `firstrun/agent.py`, `tools.py`, `runner.py`, and `report.py`. `events.py` is frozen. The only agent import the frontends require is `from firstrun.agent import run`.

Export `ANTHROPIC_API_KEY` in the terminal starting the app (do not put a key in source). `.env.example` is documentation: `.env` is not automatically loaded. The model default in the supplied plan is `claude-sonnet-5-5`; **confirm that identifier is available to your account or set FIRSTRUN_MODEL to an available model before live integration**.

```sh
uv run python -m firstrun fixtures/stale-readme --record runs/fixture.jsonl
uv run python -m firstrun --replay runs/fixture.jsonl
```

`--record` without a path writes a timestamped file in `runs/`. CLI terminal statuses have exit codes 0 (report), 2 (blocked), 1 (error). Reports are written to `out/QUICKSTART.md`, including partial or empty blocked reports. `--fast` skips replay pacing; normal replay caps every gap at 1.5 seconds.

## Scope and demo

Small, pre-vetted Python repos only. The planned runner is **sandbox-lite**, not a security boundary. A temporary directory, venv, denylist and timeouts do not isolate arbitrary repository code. No Docker, credentials in child environments, public hosted execution, or automatic PR creation.

The local fixture avoids GitHub/Wi-Fi fetches. A live agent still needs an API connection; initial dependency installation also needs connectivity. Replay needs neither API calls nor command execution once the app dependencies are installed.

The fixture README has two deliberate mistakes: a missing `requirements.txt` and a renamed `pingpong.server` module. The main demo recovers the install using `uv pip install -e ".[dev]"` and verifies with `pytest -q`.

`runs/sample.jsonl` uses checked command output and synthetic event timing. Its report and exported Markdown explicitly say it is illustrative. Capture `runs/fixture.jsonl` after Claude integration for an authentic live-agent replay. Inspect recordings before publishing: they may contain repository paths or command output.

See [TESTING.md](TESTING.md) for the manual acceptance steps and [PLAN.md](PLAN.md) for ownership and decisions.
