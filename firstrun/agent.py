"""run(target): one Claude agent, a raw Messages API tool loop, events out."""

from __future__ import annotations

import os
import time
from collections.abc import Generator, Iterator
from dataclasses import dataclass
from typing import Any

import anthropic

from firstrun import report, runner, tools
from firstrun.events import Event
from firstrun.runner import CommandResult

DEFAULT_MODEL = "claude-sonnet-5-5"
MAX_TOOL_CALLS = 14
MAX_RECOVERIES = 2
CMD_TIMEOUT_S = 90
TOTAL_BUDGET_S = 300
MAX_TOKENS = 16000
API_TIMEOUT_S = 120
API_MIN_TIMEOUT_S = 45
API_RETRIES = 1
WRAP_UP_CALLS = 3
WRAP_UP_S = 60
NUDGE = "You stopped without calling write_report. Call it now, listing only commands that ran."

SYSTEM_PROMPT = f"""You are FirstRun. You take an unfamiliar Python repository, try its setup instructions for real, \
and write a short quickstart the next developer can trust.

The repo is checked out in the working directory of run_command. FirstRun already ran `{runner.VENV_CMD}` and that \
venv is active for every command.

Work in this order:
1. Inspect: list_files, then read the README and pyproject.toml or requirements*.txt. Read independent files in \
parallel.
2. Set up: run the README's install command first, with `pip install` translated to `uv pip install`, even if you \
suspect it is stale. The point is to observe what really happens.
3. Recover: if a setup or verify command fails, read the error, then retry with one corrected command and pass \
`hypothesis`. At most {MAX_RECOVERIES} retries per failing step; after that, report the failure.
4. Verify: run the smallest command that proves the project works: `pytest -q` if there are tests, else the \
smallest smoke command from the README. If the README has a run command, try it too.
5. Report: call write_report as soon as verification passes, or as soon as FirstRun says the budget is nearly used.

Rules:
- Use `uv pip install`, never bare `pip install`. Never create another venv.
- Every command in the report must have run through run_command in this run, written exactly as you ran it. \
Anything else is "untested". Statuses are only passed, failed, untested.
- Never invent output. Verification evidence is one line copied from the real output, e.g. "1 passed in 0.02s".
- setup_steps: the setup commands in the order you ran them, failed ones included. Leave out the venv step; \
FirstRun adds it.
- obstacles: every place the README or repo misled you, with the workaround that worked.
- In summary, notes, obstacles and why, put commands and file names in backticks.
- Keep it tight: summary in two sentences, notes under ten words, read_first at most {report.MAX_READ_FIRST} files \
a newcomer should open first.
- Budget: {MAX_TOOL_CALLS} tool calls and {TOTAL_BUDGET_S} seconds for the whole run."""


class Blocked(Exception):
    """The run cannot finish; it ends with a blocked event and a partial report."""


@dataclass
class Session:
    ctx: tools.Context
    failing: CommandResult | None = None
    recoveries: int = 0
    nudged: bool = False


def run(target: str) -> Iterator[Event]:
    """Yield the events of one run. Always ends with exactly one report_ready, blocked or error event."""
    try:
        terminal = yield from _session(target)
    except (runner.WorkspaceError, anthropic.AnthropicError) as exc:
        terminal = _error(_describe(exc))
    except Exception as exc:  # noqa: BLE001 - a run must end in an event, never a crash
        terminal = _error(f"Unexpected {type(exc).__name__}: {exc}")
    yield terminal


def _session(target: str) -> Generator[Event, None, Event]:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return _error("ANTHROPIC_API_KEY is not set")
    started = time.monotonic()
    ws = yield from runner.prepare(target)
    try:
        ctx = tools.Context(
            target, ws, started, started + TOTAL_BUDGET_S, CMD_TIMEOUT_S
        )
        return (yield from _loop(Session(ctx)))
    finally:
        ws.cleanup()


def _loop(s: Session) -> Generator[Event, None, Event]:
    model = os.environ.get("FIRSTRUN_MODEL") or DEFAULT_MODEL
    client = anthropic.Anthropic(max_retries=API_RETRIES)
    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": f"Target: {s.ctx.target}. The repo is checked out and the venv is ready. Begin.",
        }
    ]
    yield Event("status", f"Planning the setup with {model}")
    try:
        while True:
            _check_budget(s)
            response = client.messages.create(
                model=model,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                tools=tools.TOOLS,
                messages=messages,
                output_config={"effort": "medium"},
                timeout=_api_timeout(s),
            )
            if response.stop_reason in ("refusal", "max_tokens"):
                raise Blocked(_no_tool_reason(response.stop_reason))
            messages.append({"role": "assistant", "content": response.content})
            uses = [block for block in response.content if block.type == "tool_use"]
            if not uses:
                if s.nudged:
                    raise Blocked(_no_tool_reason(response.stop_reason))
                s.nudged = True
                messages.append({"role": "user", "content": NUDGE})
                continue
            results: list[dict[str, Any]] = []
            for use in uses:
                outcome = yield from _dispatch(
                    s, use.name, use.input if isinstance(use.input, dict) else {}
                )
                if outcome.report is not None:
                    return _report_ready(outcome.report)
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": use.id,
                        "content": outcome.content,
                        "is_error": not outcome.ok,
                    }
                )
            messages.append({"role": "user", "content": results + _wrap_up_note(s)})
    except Blocked as hit:
        return _blocked(s, str(hit))


def _dispatch(
    s: Session, name: str, args: dict[str, Any]
) -> Generator[Event, None, tools.Outcome]:
    _check_budget(s)
    s.ctx.tool_calls += 1
    if name == "run_command":
        yield from _recovery(s, args)
    outcome = yield from tools.call(s.ctx, name, args)
    command = outcome.command
    if command is not None and command.purpose != "inspect":
        if command.ok:
            s.failing, s.recoveries = None, 0
        else:
            s.failing = command
    return outcome


def _recovery(s: Session, args: dict[str, Any]) -> Generator[Event, None, None]:
    """A setup or verify command right after a failed one is a recovery attempt."""
    if s.failing is None or args.get("purpose") == "inspect":
        return
    s.recoveries += 1
    if s.recoveries > MAX_RECOVERIES:
        raise Blocked(f"still failing after {MAX_RECOVERIES} retries: {s.failing.cmd}")
    cmd = str(args.get("cmd", "")).strip()
    hypothesis = str(
        args.get("hypothesis") or f"{s.failing.cmd} exited {s.failing.exit_code}"
    ).strip()
    yield Event(
        "recovery",
        f"Hypothesis: {hypothesis.rstrip('.')}; retrying with {cmd}",
        {
            "failed_cmd": s.failing.cmd,
            "hypothesis": hypothesis,
            "next_cmd": cmd,
            "attempt": s.recoveries,
        },
    )


def _check_budget(s: Session) -> None:
    if time.monotonic() >= s.ctx.deadline:
        raise Blocked(f"time budget of {TOTAL_BUDGET_S}s used up")
    if s.ctx.tool_calls >= MAX_TOOL_CALLS:
        raise Blocked(f"tool-call budget of {MAX_TOOL_CALLS} used up")


def _wrap_up_note(s: Session) -> list[dict[str, str]]:
    calls_left = MAX_TOOL_CALLS - s.ctx.tool_calls
    seconds_left = int(s.ctx.deadline - time.monotonic())
    if calls_left > WRAP_UP_CALLS and seconds_left > WRAP_UP_S:
        return []
    text = f"FirstRun budget: {calls_left} tool calls and {max(seconds_left, 0)}s left. Call write_report now."
    return [{"type": "text", "text": text}]


def _api_timeout(s: Session) -> float:
    """Keep one API call inside the run's budget, with room for the final write_report turn."""
    remaining = s.ctx.deadline - time.monotonic()
    return max(API_MIN_TIMEOUT_S, min(API_TIMEOUT_S, remaining))


def _no_tool_reason(stop_reason: str | None) -> str:
    if stop_reason == "refusal":
        return "the model declined the request"
    if stop_reason == "max_tokens":
        return "the model's reply hit max_tokens"
    return "the model stopped twice without writing a report"


def _report_ready(checked: report.Report) -> Event:
    status = checked["verification"]["status"]
    data = {"report": checked, "quickstart_md": report.render(checked)}
    return Event("report_ready", f"Quickstart ready: verification {status}", data)


def _blocked(s: Session, reason: str) -> Event:
    elapsed = round(time.monotonic() - s.ctx.started, 1)
    partial = report.partial(
        s.ctx.target, reason, s.ctx.ws.history, elapsed, s.ctx.tool_calls
    )
    data = {
        "reason": reason,
        "report": partial,
        "quickstart_md": report.render(partial),
    }
    return Event("blocked", f"Blocked: {reason}", data)


def _error(message: str) -> Event:
    return Event("error", f"Error: {message}", {"message": message})


def _describe(exc: Exception) -> str:
    if isinstance(exc, anthropic.APIStatusError):
        body = exc.body if isinstance(exc.body, dict) else {}
        detail = (
            body.get("error", {}).get("message")
            if isinstance(body.get("error"), dict)
            else None
        )
        return f"Claude API error {exc.status_code}: {detail or exc.message}"
    if isinstance(exc, anthropic.APIConnectionError):
        return "cannot reach the Claude API; check the network or use a replay"
    return str(exc)
