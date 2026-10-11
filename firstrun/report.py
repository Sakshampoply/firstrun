"""The report dict: validation, evidence reconciliation and QUICKSTART.md rendering."""

from __future__ import annotations

import re
import shlex
from datetime import date
from typing import Any

from firstrun.runner import VENV_CMD, CommandResult

STATUSES = ("passed", "failed", "untested")
INSTALL_CMD = re.compile(
    r"\b(pip3?|uv|poetry|pdm|pipenv|conda|npm|pnpm|yarn)\s+(\w+\s+)?(install|sync|add)\b"
)
MAX_READ_FIRST = 5

TOP = {"target": "text?", "name": "text", "summary": "text"}
READ_FIRST = {"path": "text", "why": "text?"}
STEP = {"cmd": "text", "status": "status", "note": "text?"}
VERIFICATION = {"cmd": "text?", "status": "status", "evidence": "text?"}
OBSTACLE = {"what": "text", "workaround": "text?", "resolved": "bool"}

Report = dict[str, Any]


class ReportError(ValueError):
    """The report does not match the contract in PLAN.md."""


def validate(report: object) -> Report:
    """Return a normalized copy in contract order, or raise ReportError listing every problem."""
    if not isinstance(report, dict):
        raise ReportError("report must be an object")
    problems: list[str] = []
    clean = {
        **_record(report, "report", TOP, problems),
        "read_first": _records(
            report.get("read_first", []),
            "read_first",
            READ_FIRST,
            problems,
            MAX_READ_FIRST,
        ),
        "setup_steps": _records(
            report.get("setup_steps"), "setup_steps", STEP, problems
        ),
        "verification": _record(
            report.get("verification"), "verification", VERIFICATION, problems
        ),
        "obstacles": _records(
            report.get("obstacles", []), "obstacles", OBSTACLE, problems
        ),
        "elapsed_s": _number(report, "elapsed_s", problems),
        "tool_calls": int(_number(report, "tool_calls", problems)),
    }
    if is_install(clean["verification"].get("cmd", "")):
        problems.append(
            "verification.cmd is an install; verify with the tests or a smoke command instead"
        )
    if problems:
        raise ReportError("; ".join(problems))
    return clean


def is_install(cmd: str) -> bool:
    """Installing proves nothing about whether the project runs."""
    return bool(INSTALL_CMD.search(cmd))


def reconcile(report: Report, history: list[CommandResult]) -> Report:
    """Make every status and the evidence match what actually ran in this session."""
    listed = {_argv(step["cmd"]) for step in report["setup_steps"]}
    prelude = [
        {"cmd": r.cmd, "status": _status(r), "note": _prelude_note(r.cmd)}
        for r in history
        if r.purpose == "prelude" and _argv(r.cmd) not in listed
    ]
    steps = [_reconcile_step(step, history) for step in report["setup_steps"]]
    return {
        **report,
        "setup_steps": prelude + steps,
        "verification": _reconcile_check(report["verification"], history),
    }


def partial(
    target: str,
    reason: str,
    history: list[CommandResult],
    elapsed_s: float,
    tool_calls: int,
) -> Report:
    """A report built only from the commands that ran, for runs that end blocked."""
    steps = [r for r in history if r.purpose in ("prelude", "setup")]
    checks = [r for r in history if r.purpose == "verify"]
    last = checks[-1] if checks else None
    return validate(
        {
            "target": target,
            "name": target.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git"),
            "summary": f"Not summarized: FirstRun stopped early ({reason}).",
            "setup_steps": [
                {
                    "cmd": r.cmd,
                    "status": _status(r),
                    "note": _prelude_note(r.cmd) or ("" if r.ok else _failure_note(r)),
                }
                for r in steps
            ],
            "verification": (
                {"cmd": last.cmd, "status": _status(last), "evidence": last.headline}
                if last
                else {"cmd": "", "status": "untested", "evidence": ""}
            ),
            "elapsed_s": elapsed_s,
            "tool_calls": tool_calls,
        }
    )


def render(report: Report, day: date | None = None) -> str:
    check = report["verification"]
    verdict = (
        "verified by FirstRun"
        if check["status"] == "passed"
        else "NOT verified by FirstRun"
    )
    lines = [
        f"# {report['name']}: quickstart ({verdict}, {(day or date.today()).isoformat()})",
        "",
    ]
    lines += [f"What it is: {report['summary']}", "", "## Setup"]
    lines += [
        _step_line(i, step) for i, step in enumerate(report["setup_steps"], 1)
    ] or ["- No setup commands ran."]
    lines += ["", "## Verify", _check_line(check), "", "## Gotchas"]
    lines += [_gotcha_line(obstacle) for obstacle in report["obstacles"]] or [
        "- None recorded."
    ]
    lines += ["", "## Read first"]
    lines += [
        f"- {_code(item['path'])}: {item['why']}".rstrip(": ")
        for item in report["read_first"]
    ] or ["- Nothing flagged."]
    return "\n".join(lines) + "\n"


def _step_line(index: int, step: dict[str, str]) -> str:
    note = step["note"].rstrip(".")
    return f"{index}. [{step['status']}] {_code(step['cmd'])}" + (
        f"   ({note})" if note else ""
    )


def _check_line(check: dict[str, str]) -> str:
    if not check["cmd"]:
        return "[untested] no verification command ran"
    evidence = [line.strip() for line in check["evidence"].splitlines() if line.strip()]
    return f"[{check['status']}] {_code(check['cmd'])}" + (
        f"  ->  {_code(evidence[-1])}" if evidence else ""
    )


def _prelude_note(cmd: str) -> str:
    """How the reader carries on after a step FirstRun ran for them."""
    if cmd == VENV_CMD:
        return "activate with `source .venv/bin/activate`"
    if cmd.startswith("git clone"):
        return f"then `cd {cmd.split()[-1]}`"
    return ""


def _failure_note(result: CommandResult) -> str:
    return _code(result.headline) if result.headline else f"exit {result.exit_code}"


def _code(text: str) -> str:
    """Inline code, so names like __init__.py and <workspace> survive Markdown."""
    return f"`` {text} ``" if "`" in text else f"`{text}`"


def _gotcha_line(obstacle: dict[str, Any]) -> str:
    what, fix = obstacle["what"].rstrip("."), obstacle["workaround"]
    if not obstacle["resolved"]:
        return f"- {what}. Unresolved" + (f"; tried: {fix}" if fix else ".")
    return f"- {what}. Fix: {fix}" if fix else f"- {what}."


def _reconcile_step(
    step: dict[str, str], history: list[CommandResult]
) -> dict[str, str]:
    runs = _runs_of(step["cmd"], history)
    if not runs:
        return {**step, "status": "untested"}
    statuses = [_status(r) for r in runs]
    return {
        **step,
        "status": step["status"] if step["status"] in statuses else statuses[-1],
    }


def _reconcile_check(
    check: dict[str, str], history: list[CommandResult]
) -> dict[str, str]:
    runs = _runs_of(check["cmd"], history) if check["cmd"] else []
    if not runs:
        return {**check, "status": "untested", "evidence": ""}
    run = next((r for r in reversed(runs) if _status(r) == check["status"]), runs[-1])
    quoted = check["evidence"] and check["evidence"] in run.output
    return {
        **check,
        "status": _status(run),
        "evidence": check["evidence"] if quoted else run.headline,
    }


def _runs_of(cmd: str, history: list[CommandResult]) -> list[CommandResult]:
    argv = _argv(cmd)
    return [r for r in history if _argv(r.cmd) == argv]


def _argv(cmd: str) -> tuple[str, ...]:
    """Compare commands as the shell would see them, so quoting style does not matter."""
    try:
        return tuple(shlex.split(cmd))
    except ValueError:
        return tuple(cmd.split())


def _status(result: CommandResult) -> str:
    return "passed" if result.ok else "failed"


def _records(
    value: object,
    where: str,
    spec: dict[str, str],
    problems: list[str],
    limit: int | None = None,
) -> list:
    if not isinstance(value, list):
        problems.append(f"{where} must be a list")
        return []
    if limit is not None and len(value) > limit:
        problems.append(f"{where} has {len(value)} entries; the maximum is {limit}")
    return [
        _record(item, f"{where}[{i}]", spec, problems) for i, item in enumerate(value)
    ]


def _record(
    value: object, where: str, spec: dict[str, str], problems: list[str]
) -> dict[str, Any]:
    if not isinstance(value, dict):
        problems.append(f"{where} must be an object")
        return {}
    clean: dict[str, Any] = {}
    for key, kind in spec.items():
        item = value.get(key)
        if kind == "status":
            if item not in STATUSES:
                problems.append(
                    f"{where}.{key} must be passed, failed or untested, not {item!r}"
                )
            clean[key] = item
        elif kind == "bool":
            if not isinstance(item, bool):
                problems.append(f"{where}.{key} must be true or false")
            clean[key] = bool(item)
        else:
            item = "" if item is None and kind == "text?" else item
            if not isinstance(item, str) or (kind == "text" and not item.strip()):
                problems.append(
                    f"{where}.{key} must be a {'non-empty ' if kind == 'text' else ''}string"
                )
            clean[key] = str(item or "").strip()
    return clean


def _number(report: dict[str, Any], key: str, problems: list[str]) -> float:
    value = report.get(key, 0)
    if isinstance(value, bool) or not isinstance(value, int | float):
        problems.append(f"{key} must be a number")
        return 0
    return value
