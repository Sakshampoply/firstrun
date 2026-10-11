"""The five agent tools: JSON schemas for the Messages API and their implementations."""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable, Generator
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from firstrun import report, runner
from firstrun.events import Event
from firstrun.runner import CommandResult, Workspace

SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache"}
MAX_SEARCH_MATCHES = 30
MAX_SEARCH_FILE_BYTES = 1_000_000

_STATUS = {"type": "string", "enum": list(report.STATUSES)}
_TEXT = {"type": "string"}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_files",
        "description": "List the repo tree, skipping .git, .venv, node_modules and __pycache__. Directories end with /.",
        "input_schema": {
            "type": "object",
            "properties": {
                "max_depth": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 6,
                    "default": 3,
                },
                "max_entries": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 500,
                    "default": 200,
                },
            },
        },
    },
    {
        "name": "read_file",
        "description": "Read a text file. Paths are relative to the repo root.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": _TEXT,
                "max_bytes": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20000,
                    "default": 6000,
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "search",
        "description": f"Regex search over repo files matching a glob. Returns up to {MAX_SEARCH_MATCHES} matches "
        "as path:line:text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": _TEXT,
                "glob": {"type": "string", "default": "**/*.py"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "run_command",
        "description": "Run a shell command from the repo root with the project venv active. Returns exit_code, "
        "duration_s and the last 3000 chars of stdout and stderr. 90 s timeout. sudo, rm -rf, chmod, chown, docker, "
        "git push, curl|sh and paths outside the repo are rejected with exit code 126.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cmd": _TEXT,
                "purpose": {
                    "type": "string",
                    "enum": ["inspect", "setup", "verify"],
                    "description": "inspect: looking around. setup: installing. verify: proving the project works.",
                },
                "hypothesis": {
                    "type": "string",
                    "description": "Required when the previous setup or verify command failed: one short sentence "
                    "on what went wrong and why this command fixes it.",
                },
            },
            "required": ["cmd", "purpose"],
        },
    },
    {
        "name": "write_report",
        "description": "Submit the final quickstart and end the run. FirstRun re-checks the report against what "
        "actually ran: commands that never ran become untested and statuses follow the real exit codes. "
        "An invalid report is rejected with the reason.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Project name."},
                "summary": {
                    "type": "string",
                    "description": "Two sentences on what the project does.",
                },
                "read_first": {
                    "type": "array",
                    "maxItems": report.MAX_READ_FIRST,
                    "items": {
                        "type": "object",
                        "properties": {"path": _TEXT, "why": _TEXT},
                        "required": ["path", "why"],
                    },
                },
                "setup_steps": {
                    "type": "array",
                    "description": "Setup commands in the order you ran them, failed ones included.",
                    "items": {
                        "type": "object",
                        "properties": {"cmd": _TEXT, "status": _STATUS, "note": _TEXT},
                        "required": ["cmd", "status"],
                    },
                },
                "verification": {
                    "type": "object",
                    "properties": {
                        "cmd": _TEXT,
                        "status": _STATUS,
                        "evidence": {
                            "type": "string",
                            "description": "One line copied from the real output.",
                        },
                    },
                    "required": ["cmd", "status", "evidence"],
                },
                "obstacles": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "what": _TEXT,
                            "workaround": _TEXT,
                            "resolved": {"type": "boolean"},
                        },
                        "required": ["what", "workaround", "resolved"],
                    },
                },
            },
            "required": [
                "name",
                "summary",
                "read_first",
                "setup_steps",
                "verification",
                "obstacles",
            ],
        },
    },
]


@dataclass
class Context:
    target: str
    ws: Workspace
    started: float
    deadline: float
    cmd_timeout_s: float
    tool_calls: int = 0


@dataclass
class Outcome:
    content: str
    ok: bool = True
    report: report.Report | None = None
    command: CommandResult | None = None


Handler = Callable[[Context, dict[str, Any]], Generator[Event, None, Outcome]]


def call(
    ctx: Context, name: str, args: dict[str, Any]
) -> Generator[Event, None, Outcome]:
    """Run one tool call. run_command reports through command events; other tools emit tool_call."""
    handler = HANDLERS.get(name)
    if handler is None:
        outcome = Outcome(f"Unknown tool: {name}", ok=False)
    else:
        try:
            outcome = yield from handler(ctx, args)
        except (KeyError, TypeError, ValueError, OSError) as exc:
            outcome = Outcome(f"Invalid input for {name}: {exc}", ok=False)
    if not outcome.ok:
        yield Event(
            "tool_result",
            outcome.content,
            {"name": name, "ok": False, "summary": outcome.content},
        )
    return outcome


def _list_files(ctx: Context, args: dict[str, Any]) -> Generator[Event, None, Outcome]:
    max_depth = _clamp(args.get("max_depth", 3), 1, 6)
    max_entries = _clamp(args.get("max_entries", 200), 1, 500)
    yield Event("tool_call", "Listing files", {"name": "list_files", "input": args})
    entries: list[str] = []
    for here, dirs, files in _walk(ctx.ws.repo):
        entries += [f"{(here / d).as_posix()}/" for d in dirs] + [
            (here / f).as_posix() for f in files
        ]
        if len(here.parts) + 1 >= max_depth:
            dirs.clear()
    entries.sort()
    hidden = len(entries) - max_entries
    return Outcome(
        "\n".join(entries[:max_entries])
        + (f"\n... {hidden} more not shown" if hidden > 0 else "")
    )


def _read_file(ctx: Context, args: dict[str, Any]) -> Generator[Event, None, Outcome]:
    rel = str(args["path"])
    max_bytes = _clamp(args.get("max_bytes", 6000), 1, 20000)
    yield Event("tool_call", f"Reading {rel}", {"name": "read_file", "input": args})
    path = _inside(ctx.ws.repo, rel)
    if not path.is_file():
        return Outcome(f"Not found: {rel}", ok=False)
    data = path.read_bytes()
    text = data[:max_bytes].decode("utf-8", errors="replace")
    return Outcome(
        text
        + (
            f"\n[truncated: {max_bytes} of {len(data)} bytes]"
            if len(data) > max_bytes
            else ""
        )
    )


def _search(ctx: Context, args: dict[str, Any]) -> Generator[Event, None, Outcome]:
    pattern, glob = str(args["pattern"]), str(args.get("glob") or "**/*.py")
    yield Event(
        "tool_call",
        f"Searching {glob} for {pattern}",
        {"name": "search", "input": args},
    )
    try:
        regex = re.compile(pattern)
    except re.error:
        regex = re.compile(re.escape(pattern))
    matches: list[str] = []
    for here, _, files in _walk(ctx.ws.repo):
        for name in files:
            rel = (here / name).as_posix()
            if _glob_match(rel, glob):
                matches += _grep(
                    ctx.ws.repo / rel, rel, regex, MAX_SEARCH_MATCHES - len(matches)
                )
            if len(matches) >= MAX_SEARCH_MATCHES:
                return Outcome(
                    "\n".join(matches) + f"\n[stopped at {MAX_SEARCH_MATCHES} matches]"
                )
    return Outcome("\n".join(matches) or "No matches.")


def _run_command(ctx: Context, args: dict[str, Any]) -> Generator[Event, None, Outcome]:
    cmd = str(args["cmd"]).strip()
    if not cmd:
        raise ValueError("cmd is empty")
    purpose = (
        args.get("purpose")
        if args.get("purpose") in ("inspect", "setup", "verify")
        else "setup"
    )
    timeout = min(ctx.cmd_timeout_s, max(1.0, ctx.deadline - time.monotonic()))
    result = yield from runner.run_command(ctx.ws, cmd, timeout, purpose)
    if purpose == "verify" and result.ok:
        yield Event("status", f"Verified: {cmd}, {result.headline or 'exit 0'}")
    payload = {k: v for k, v in result.event_data().items() if k != "cmd"}
    return Outcome(json.dumps(payload, ensure_ascii=False), command=result)


def _write_report(
    ctx: Context, args: dict[str, Any]
) -> Generator[Event, None, Outcome]:
    yield Event(
        "tool_call", "Writing QUICKSTART.md", {"name": "write_report", "input": args}
    )
    draft = {
        **args,
        "target": ctx.target,
        "elapsed_s": round(time.monotonic() - ctx.started, 1),
        "tool_calls": ctx.tool_calls,
    }
    try:
        checked = report.reconcile(report.validate(draft), ctx.ws.history)
    except report.ReportError as exc:
        return Outcome(
            f"Report rejected: {exc}. Fix it and call write_report again.", ok=False
        )
    return Outcome("Report accepted.", report=checked)


HANDLERS: dict[str, Handler] = {
    "list_files": _list_files,
    "read_file": _read_file,
    "search": _search,
    "run_command": _run_command,
    "write_report": _write_report,
}


def _walk(root: Path) -> Generator[tuple[Path, list[str], list[str]], None, None]:
    """os.walk relative to root, sorted, with SKIP_DIRS pruned. Callers may prune dirs further."""
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = sorted(
            d for d in dirs if d not in SKIP_DIRS and not d.endswith(".egg-info")
        )
        yield Path(dirpath).relative_to(root), dirs, sorted(files)


def _glob_match(rel: str, glob: str) -> bool:
    return fnmatch(rel, glob) or (glob.startswith("**/") and fnmatch(rel, glob[3:]))


def _grep(path: Path, rel: str, regex: re.Pattern[str], limit: int) -> list[str]:
    if path.stat().st_size > MAX_SEARCH_FILE_BYTES:
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    hits = [
        f"{rel}:{n}:{line.strip()[:200]}"
        for n, line in enumerate(text.splitlines(), 1)
        if regex.search(line)
    ]
    return hits[:limit]


def _inside(repo: Path, rel: str) -> Path:
    path = (repo / rel).resolve()
    if not path.is_relative_to(repo):
        raise ValueError(f"{rel} is outside the repo")
    return path


def _clamp(value: Any, low: int, high: int) -> int:
    return max(low, min(high, int(value)))
