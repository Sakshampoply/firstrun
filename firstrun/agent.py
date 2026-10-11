from typing import Iterator
from firstrun.events import Event


def run(target: str) -> Iterator[Event]:
    yield Event("status", f"agent stub: {target}")
    yield Event("blocked", "agent not implemented", {"reason": "stub", "report": {}, "quickstart_md": ""})
