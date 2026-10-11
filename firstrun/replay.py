"""Replay saved events without calling a model or running repository code."""
import time
from typing import Iterator
from firstrun.events import Event, read_jsonl


def replay(path: str, fast: bool = False) -> Iterator[Event]:
    previous = None
    for event in read_jsonl(path):
        if previous is not None and not fast:
            time.sleep(min(1.5, max(0.0, event.ts - previous)))
        yield event
        previous = event.ts
