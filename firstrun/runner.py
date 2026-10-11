"""Sandbox-lite: a scratch copy of the target repo, a uv venv, and guarded shell commands.

Not a security boundary. Demo targets are pre-vetted.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Generator
from dataclasses import dataclass, field
from pathlib import Path

from firstrun.events import Event

TAIL_CHARS = 3000
DENIED_EXIT = 126
TIMEOUT_EXIT = 124
DRAIN_S = 5
VENV_CMD = "uv venv .venv"
STRICT_SHELL = "set -eo pipefail"
PYTHON_MARKERS = ("pyproject.toml", "setup.py", "setup.cfg")
MAX_REPO_FILES = 2000
GITHUB_URL = re.compile(r"^https://github\.com/[\w.-]+/[\w.-]+?(\.git)?/?$")
SECRET_ENV = re.compile(r"KEY|TOKEN|SECRET|PASSWORD", re.IGNORECASE)
COPY_SKIP = shutil.ignore_patterns(
    ".git", ".venv", "__pycache__", "*.egg-info", ".pytest_cache"
)
DENYLIST = (
    (re.compile(r"\bsudo\b"), "sudo"),
    (re.compile(r"\brm\s+(-\w*[rf]|--recursive|--force)"), "rm -rf"),
    (
        re.compile(r"\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?(\w*sh|python3?)\b"),
        "piping a download into a shell",
    ),
    (re.compile(r"\bchmod\b"), "chmod"),
    (re.compile(r"\bchown\b"), "chown"),
    (re.compile(r"\bdocker\b"), "docker"),
    (re.compile(r"\bgit\s+push\b"), "git push"),
    (
        re.compile(r"\b(npm|npx|pnpm|yarn|bun|cargo|brew|apt|apt-get)\b"),
        "non-Python tooling",
    ),
)


class WorkspaceError(Exception):
    """The target could not be turned into a runnable workspace."""


@dataclass
class CommandResult:
    cmd: str
    exit_code: int
    duration_s: float
    stdout_tail: str
    stderr_tail: str
    purpose: str = "setup"

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    @property
    def output(self) -> str:
        return "\n".join(
            part for part in (self.stdout_tail, self.stderr_tail) if part.strip()
        )

    @property
    def headline(self) -> str:
        """The most telling output line: the last error line on failure, else the last line."""
        lines = [line.strip() for line in self.output.splitlines() if line.strip()]
        if not lines:
            return ""
        if not self.ok:
            errors = [
                line
                for line in lines
                if re.match(r"(error|fatal|E\s)", line, re.IGNORECASE)
            ]
            return (errors or lines)[-1][:160]
        return lines[-1][:160]

    def event_data(self) -> dict[str, object]:
        return {
            "cmd": self.cmd,
            "exit_code": self.exit_code,
            "duration_s": self.duration_s,
            "stdout_tail": self.stdout_tail,
            "stderr_tail": self.stderr_tail,
        }


@dataclass
class Workspace:
    root: Path
    repo: Path
    history: list[CommandResult] = field(default_factory=list)

    @property
    def prelude(self) -> list[CommandResult]:
        """Commands FirstRun ran before the agent started (clone, venv)."""
        return [result for result in self.history if result.purpose == "prelude"]

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


def prepare(target: str) -> Generator[Event, None, Workspace]:
    """Copy or clone the target into a temp dir, check it is a small Python repo, create its venv."""
    root = Path(tempfile.mkdtemp(prefix="firstrun-")).resolve()
    ws = Workspace(root=root, repo=root / "repo")
    try:
        if target.startswith("https://"):
            yield from _clone(ws, target)
        else:
            yield Event("status", f"Copying {target} into a scratch workspace")
            _copy(ws, target)
        _check_scope(ws.repo)
        yield Event("status", "Creating a fresh venv")
        venv = yield from _run(ws, VENV_CMD, ws.repo, 120, "prelude")
        if not venv.ok:
            raise WorkspaceError(f"uv venv failed: {venv.headline}")
    except BaseException:
        ws.cleanup()
        raise
    return ws


def run_command(
    ws: Workspace, cmd: str, timeout_s: float, purpose: str
) -> Generator[Event, None, CommandResult]:
    """Run one agent command in the repo, unless the denylist rejects it."""
    reason = deny_reason(cmd, ws.repo)
    if reason is None:
        return (yield from _run(ws, cmd, ws.repo, timeout_s, purpose))
    yield Event("command_started", f"Running: {cmd}", {"cmd": cmd})
    result = CommandResult(
        cmd,
        DENIED_EXIT,
        0.0,
        "",
        f"Rejected by FirstRun: {reason} is not allowed",
        purpose,
    )
    ws.history.append(result)
    yield Event(
        "command_finished", f"Rejected: {reason} is not allowed", result.event_data()
    )
    return result


def deny_reason(cmd: str, repo: Path) -> str | None:
    for pattern, label in DENYLIST:
        if pattern.search(cmd):
            return label
    for token in _tokens(cmd):
        for part in token.split("="):
            if part.startswith("~"):
                return f"leaving the repo ({part})"
            if part.startswith("/") or ".." in Path(part).parts:
                resolved = (repo / part).resolve()
                if resolved != Path("/dev/null") and not resolved.is_relative_to(repo):
                    return f"leaving the repo ({part})"
    return None


def _tokens(cmd: str) -> list[str]:
    try:
        lexer = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError:
        return cmd.split()


def _check_scope(repo: Path) -> None:
    if not any((repo / name).is_file() for name in PYTHON_MARKERS) and not any(
        repo.glob("requirements*.txt")
    ):
        raise WorkspaceError(
            "Out of scope: no pyproject.toml, setup.py or requirements.txt at the repo root. "
            "FirstRun handles small Python repos."
        )
    files = sum(len(names) for _, _, names in _walk_files(repo))
    if files > MAX_REPO_FILES:
        raise WorkspaceError(
            f"Out of scope: {files} files. FirstRun handles small repos (up to {MAX_REPO_FILES})."
        )


def _walk_files(repo: Path) -> Generator[tuple[str, list[str], list[str]], None, None]:
    for dirpath, dirs, names in os.walk(repo):
        dirs[:] = [d for d in dirs if d != ".git"]
        yield dirpath, dirs, names


def _copy(ws: Workspace, target: str) -> None:
    source = Path(target).expanduser()
    if not source.is_dir():
        raise WorkspaceError(f"Not a directory: {target}")
    shutil.copytree(source, ws.repo, ignore=COPY_SKIP)


def _clone(ws: Workspace, url: str) -> Generator[Event, None, None]:
    if not GITHUB_URL.match(url):
        raise WorkspaceError(
            f"Only public https://github.com/owner/repo URLs are supported: {url}"
        )
    yield Event("status", f"Cloning {url}")
    cmd = f"git clone --depth 1 {shlex.quote(url)} {ws.repo.name}"
    result = yield from _run(ws, cmd, ws.root, 90, "prelude")
    if not result.ok:
        raise WorkspaceError(f"git clone failed: {result.headline}")


def _run(
    ws: Workspace, cmd: str, cwd: Path, timeout_s: float, purpose: str
) -> Generator[Event, None, CommandResult]:
    yield Event("command_started", f"Running: {cmd}", {"cmd": cmd})
    result = _execute(cmd, cwd, _env(ws.repo / ".venv"), timeout_s, purpose)
    result.stdout_tail = result.stdout_tail.replace(str(ws.root), "<workspace>")
    result.stderr_tail = result.stderr_tail.replace(str(ws.root), "<workspace>")
    ws.history.append(result)
    yield Event("command_finished", _outcome(result), result.event_data())
    return result


def _outcome(result: CommandResult) -> str:
    if result.ok:
        return f"Passed in {result.duration_s:.1f}s: {result.cmd}"
    if result.exit_code == TIMEOUT_EXIT:
        return f"Timed out after {result.duration_s:.0f}s: {result.cmd}"
    return f"Failed (exit {result.exit_code}): {result.headline or result.cmd}"


def _execute(
    cmd: str, cwd: Path, env: dict[str, str], timeout_s: float, purpose: str
) -> CommandResult:
    started = time.monotonic()
    # Strict bash: a failure anywhere in a `;` chain or a pipe fails the whole step.
    proc = subprocess.Popen(
        ["/bin/bash", "-c", f"{STRICT_SHELL}\n{cmd}"],
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout_s)
        exit_code = proc.returncode
    except subprocess.TimeoutExpired:
        _kill(proc)
        stdout, stderr = _drain(proc)
        exit_code, stderr = (
            TIMEOUT_EXIT,
            f"{stderr}\nKilled by FirstRun after {timeout_s:.0f}s",
        )
    except BaseException:
        _kill(proc)
        raise
    duration = round(time.monotonic() - started, 2)
    return CommandResult(
        cmd, exit_code, duration, stdout[-TAIL_CHARS:], stderr[-TAIL_CHARS:], purpose
    )


def _kill(proc: subprocess.Popen[str]) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        pass


def _drain(proc: subprocess.Popen[str]) -> tuple[str, str]:
    """Output of a killed command, giving up if a detached child still holds the pipes."""
    try:
        return proc.communicate(timeout=DRAIN_S)
    except subprocess.TimeoutExpired as exc:
        for pipe in (proc.stdout, proc.stderr):
            if pipe:
                pipe.close()
        proc.wait()
        return _decode(exc.output), _decode(exc.stderr)


def _decode(data: str | bytes | None) -> str:
    if isinstance(data, bytes):
        return data.decode(errors="replace")
    return data or ""


def _env(venv: Path) -> dict[str, str]:
    """Inherited env minus secrets, with the target venv active instead of FirstRun's own.

    GIT_CONFIG_* goes as a set: dropping only GIT_CONFIG_KEY_n would break every git command.
    """
    env = {
        k: v
        for k, v in os.environ.items()
        if not SECRET_ENV.search(k) and not k.startswith(("ANTHROPIC_", "GIT_CONFIG_"))
    }
    own_bin = str(Path(sys.prefix) / "bin")
    path = [p for p in env.get("PATH", "").split(os.pathsep) if p and p != own_bin]
    env["PATH"] = os.pathsep.join([str(venv / "bin"), *path])
    env["VIRTUAL_ENV"] = str(venv)
    env.pop("PYTHONHOME", None)
    env["PIP_REQUIRE_VIRTUALENV"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.setdefault("UV_LINK_MODE", "copy")
    return env
