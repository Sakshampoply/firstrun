# FirstRun manual acceptance checklist

Run all commands from the FirstRun repository directory.

## 1. Install

```sh
uv sync
```

Expected: Python 3.12 environment and dependencies installed. No API key is needed for any replay check.

## 2. CLI replay

```sh
uv run python -m firstrun --replay runs/sample.jsonl --fast
```

Expected: REPLAY and illustrative-sample labels; missing requirements.txt failure; a recovery hypothesis; successful editable install; `1 passed`; a complete quickstart panel. Exit code 0. Open `out/QUICKSTART.md`: setup steps, verification, gotcha and reading list must be present, with the illustrative disclaimer.

Repeat without `--fast`. Expected: same result, with short pauses capped at 1.5 seconds.

## 3. Browser replay and download

```sh
uv run streamlit run firstrun/ui.py
```

Open http://localhost:8501. Switch **Source** to **Replay**, choose **sample.jsonl**, enable **Fast replay**, click **Replay ▶**.

Expected: visible REPLAY label; activity appended in order; failed install, recovery and successful pytest; Outcome/Commands/Recoveries/Time tiles; a report card with passed/failed/untested chips, verification evidence, gotchas and reading list; the raw file on the QUICKSTART.md tab. Output blocks contain at most six lines. Download QUICKSTART.md and compare its content to the CLI file. The feed and report should remain visible after clicking Download or changing another control.

Turn off Fast replay and run again. Expected: events appear incrementally; the previous run is cleared.

## 4. Integrated agent: missing-key error and recording

```sh
ANTHROPIC_API_KEY= uv run python -m firstrun fixtures/stale-readme --record out/missing-key.jsonl
```

Expected: `Error: ANTHROPIC_API_KEY is not set`, exit code 1, no traceback. The recording contains exactly one `error` terminal event; no workspace or API call is attempted. Replay it with `--replay out/missing-key.jsonl --fast`: expect the same error with the REPLAY label and exit 1.

Start Streamlit without a key, choose Live, and Run. Expected: a clean error banner in the report panel. With recording enabled a new `runs/live-YYYYmmdd-HHMMSS.jsonl` appears; `runs/fixture.jsonl` remains untouched. Repeat: each attempt gets its own filename. Remove disposable error recordings after checking so they do not clutter the selector.

If a key is available, proceed to step 7 for the live acceptance check. A budget-limited run should show a blocked warning and a downloadable partial quickstart (exit 2), rather than a stub result.

## 5. Missing recording

```sh
uv run python -m firstrun --replay runs/does-not-exist.jsonl --fast
```

Expected: readable ERROR, exit code 1, no Python traceback.

## 6. Fixture itself (independent of agent)

```sh
cd fixtures/stale-readme
uv venv .venv
source .venv/bin/activate
uv pip install -r requirements.txt
uv pip install -e ".[dev]"
pytest -q
python -m pingpong.app
```

Expected: first install fails because requirements.txt is absent; editable install succeeds; pytest reports one passing test; module prints `pong`. The commands also warm uv's package cache. Run `deactivate` then `cd ../..` before continuing.

## 7. Live agent acceptance

Export ANTHROPIC_API_KEY in your terminal and confirm FIRSTRUN_MODEL is available in your account. Do not paste credentials into a recording or commit them.

```sh
uv run python -m firstrun fixtures/stale-readme --record runs/fixture.jsonl
```

Expected: real command failure, recovery event, successful install and pytest; exactly one `report_ready` terminal event; factual QUICKSTART.md with actual command evidence. Verify the report does not mark unexecuted commands passed. Repeat in Streamlit Live mode. Expect a green Verified line, plain filenames such as __init__.py, and command headlines matching the agent messages. Download the report. UI recordings use a fresh live timestamped path; the CLI hero recording remains unchanged.

Replay `runs/fixture.jsonl` with the key unset in another terminal. Expected: no API required; same report and explicit REPLAY label. Stop Streamlit with Ctrl-C when done.

## 8. Two-minute rehearsal

Say: “FirstRun tries a repo's setup instructions and gives the next developer a quickstart backed by real runs.” Use the fixture. Point to failed install, recovery, passing pytest, then download. If live API connectivity fails, use the saved run and say it is a replay. Do not present sample.jsonl as a live agent recording.

## 9. Lint and format

```sh
uvx ruff check .
uvx ruff format --check .
```

Expected: both exit 0. Frozen events.py and fixtures are excluded; PLAN.md is excluded from formatting to preserve its verbatim event contract. Do not edit the four Claude modules or events.py during frontend polish.
