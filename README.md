# FirstRun

Paste a repo, get a quickstart the agent has actually tested.

FirstRun reads a small Python repository, attempts its setup, investigates failures, and produces QUICKSTART.md with actual command evidence. One Claude tool loop drives the run; the CLI and Streamlit UI display its events. Restart Streamlit after pulling new agent modules so it loads the current implementation.

## Three commands

Run from this repository's directory with [uv](https://docs.astral.sh/uv/) installed. uv provides Python 3.12 and the app dependencies.

```sh
uv sync
uv run python -m firstrun --replay runs/sample.jsonl --fast
uv run streamlit run firstrun/ui.py
```

In the UI switch **Source** to **Replay**, choose `fixture.jsonl` (real run) or `sample.jsonl` (illustrative), then **Replay ▶**. The activity feed shows a failed install, recovery and passing pytest; the report can be downloaded as QUICKSTART.md. The sample is illustrative: actual fixture command checks, scripted narration and synthetic event timing.

## Live run

Live needs `ANTHROPIC_API_KEY` exported in the terminal launching FirstRun. `FIRSTRUN_MODEL` is optional; the default is `claude-sonnet-5-5`. Set the override if your account uses another compatible model. `.env.example` documents these variables; the app does not automatically load `.env`.

```sh
export ANTHROPIC_API_KEY="your-key"
uv run python -m firstrun fixtures/stale-readme --record runs/fixture.jsonl
```

The fixture deliberately has a missing `requirements.txt` and a renamed launch module. The agent should observe the install failure, recover with `uv pip install -e ".[dev]"`, and verify with `pytest -q`.

The CLI writes `out/QUICKSTART.md` for completed or blocked runs. Exit codes: 0 report ready, 2 blocked with a partial report, 1 error. Missing credentials produce a clean error with no traceback. `--record` without a path selects a timestamped recording name.

The UI saves each live attempt to a new `runs/live-YYYYmmdd-HHMMSS.jsonl` file (with a numeric suffix if needed). It preserves `runs/fixture.jsonl`, your known-good fallback. Only publish a hero recording after checking that it contains a failed install, recovery, successful install and passing pytest.

## Replay and demo

Replay is **always labelled REPLAY**, uses the saved timestamps with gaps capped at 1.5 seconds, and makes no API calls or repository commands. `--fast` removes pacing.

```sh
uv run python -m firstrun --replay runs/fixture.jsonl
```

The local fixture avoids a GitHub fetch. Live still needs API connectivity; use a saved run if the connection fails. Package installation can use a prewarmed uv cache. `runs/sample.jsonl` is illustrative and must be presented as such; a real agent recording is written only by running the agent.

Use small, pre-vetted Python targets. The runner is sandbox-lite: a scratch copy, isolated venv, command denylist, scrubbed child environment and timeouts. It is not a security boundary for arbitrary code.

## Demo

Two-minute script:

1. Say: “FirstRun tries a repo's setup instructions and hands the next developer a quickstart backed by real runs.”
2. Select **Live**, enter `fixtures/stale-readme`, then click **Run ▶**. Point out the missing requirements file, the install recovery, the stale module and its recovery, then the passing pytest and `pong` output. The stat tiles show commands, two recoveries and elapsed time.
3. Point to the **Verified** outcome and report. Click **⬇ Download QUICKSTART.md** to hand the next developer the tested instructions.
4. If the connection fails, select **Replay**, choose `fixture.jsonl`, then click **Replay ▶**. Say: “This is a replay of the verified laptop run.” The REPLAY pill remains visible while scrolling. Use **Fast replay** only if you need to skip the recorded pauses.

Pre-demo checklist:

- Load the key from the ignored `.env` in the terminal: `set -a`, `source .env`, `set +a`. Never show the file or key on the projector.
- Stop the old Streamlit process and restart from this repo root: `uv run streamlit run firstrun/ui.py`.
- Confirm uv's package cache is warm; the successful fixture runs warm it already.
- Set browser zoom for the projector. Rehearsed at 1280×720 and 100% zoom; check the actual display before presenting.
- Run `uv run python -m firstrun --replay runs/fixture.jsonl --fast` and confirm **Quickstart ready: verification passed**, exit 0 and two recoveries.

## Checks

```sh
uvx ruff check .
uvx ruff format --check .
ANTHROPIC_API_KEY= uv run python -m firstrun fixtures/stale-readme
```

The last command intentionally exits 1. See [TESTING.md](TESTING.md) for browser, download and live-demo acceptance steps. [PLAN.md](PLAN.md) records the architecture and decisions; [AGENTS.md](AGENTS.md) defines file ownership.
