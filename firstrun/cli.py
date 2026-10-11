"""Event-only terminal frontend."""
import argparse
from datetime import datetime
from pathlib import Path
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from firstrun.events import Event, write_jsonl
from firstrun.replay import replay

TERMINAL = {"report_ready", "blocked", "error"}


def show(console: Console, event: Event) -> None:
    data = event.data
    if event.type == "command_started":
        console.print(Text("$ " + data.get("cmd", ""), style="bold cyan"))
    elif event.type == "command_finished":
        ok = data.get("exit_code") == 0
        console.print(Text(f"{'PASS' if ok else 'FAIL'} · exit {data.get('exit_code')} · {data.get('duration_s', 0):.2f}s", style="green" if ok else "red"))
        for key in ("stdout_tail", "stderr_tail"):
            if data.get(key):
                console.print(Text(data[key].rstrip()))
    elif event.type == "recovery":
        console.print(Panel(Text(data.get("hypothesis", event.msg)), title="RECOVERY", border_style="yellow"))
        if data.get("next_cmd"):
            console.print(Text("Next: " + data["next_cmd"], style="yellow"))
    elif event.type in {"report_ready", "blocked"}:
        if event.type == "blocked":
            console.print(Text("BLOCKED: " + data.get("reason", event.msg), style="yellow"))
        markdown = data.get("quickstart_md", "")
        Path("out").mkdir(exist_ok=True)
        output = Path("out/QUICKSTART.md")
        output.write_text(markdown, encoding="utf-8")
        console.print(Panel(Markdown(markdown or "No verified report yet. Agent implementation is pending."), title="Quickstart", border_style="green" if event.type == "report_ready" else "yellow"))
        console.print(Text(f"Saved: {output.resolve()}"))
    elif event.type == "error":
        console.print(Text("ERROR: " + data.get("message", event.msg), style="red"))
    else:
        msg = event.msg or str(data.get("summary", data.get("name", event.type)))
        console.print(Text(msg, style="dim" if event.type == "status" else "white"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="FirstRun: a quickstart backed by actual setup attempts")
    parser.add_argument("target", nargs="?")
    parser.add_argument("--record", nargs="?", const="auto", metavar="PATH", help="save live events (default: timestamped runs file)")
    parser.add_argument("--replay", metavar="PATH")
    parser.add_argument("--fast", action="store_true", help="skip replay delays")
    args = parser.parse_args(argv)
    if not args.replay and not args.target:
        parser.error("provide a target or --replay PATH")
    if args.replay and (args.target or args.record):
        parser.error("--replay cannot be combined with a target or --record")
    console = Console()
    console.print(Panel("FirstRun · verified repository onboarding", border_style="cyan"))
    terminal = None
    try:
        if args.replay:
            console.print(Text(f"REPLAY · {args.replay} · recorded events; no commands executed", style="bold yellow"))
            events = replay(args.replay, fast=args.fast)
        else:
            from firstrun.agent import run
            events = run(args.target)
        if args.record:
            path = Path("runs") / (datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".jsonl") if args.record == "auto" else Path(args.record)
            path.parent.mkdir(parents=True, exist_ok=True)
            events = write_jsonl(str(path), events)
            console.print(Text(f"Recording: {path}"))
        for event in events:
            if terminal is not None:
                raise ValueError("event stream continued after its terminal event")
            show(console, event)
            if event.type in TERMINAL:
                terminal = event.type
        if terminal is None:
            raise ValueError("event stream ended without a terminal event")
        return 0 if terminal == "report_ready" else 2 if terminal == "blocked" else 1
    except KeyboardInterrupt:
        console.print("Interrupted.")
        return 130
    except Exception as exc:
        console.print(Text(f"ERROR: {exc}", style="red"))
        return 1
