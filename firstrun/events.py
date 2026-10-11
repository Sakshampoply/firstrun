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
