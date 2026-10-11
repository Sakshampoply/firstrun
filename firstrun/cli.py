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


def output_tail(data: dict) -> str:
    """Keep the combined command output to six lines for the demo feed."""
    output = "\n".join(
        data.get(key, "").rstrip()
        for key in ("stdout_tail", "stderr_tail")
        if data.get(key)
    )
    return "\n".join(output.splitlines()[-6:])


def show(console: Console, event: Event) -> None:
    data = event.data
    if event.type == "command_started":
        console.print(Text("$ " + data.get("cmd", ""), style="bold cyan"))
    elif event.type == "command_finished":
        ok = data.get("exit_code") == 0
        fallback = (
            f"{'Passed' if ok else 'Failed'} (exit {data.get('exit_code')}): "
            f"{data.get('cmd', '')}"
        )
        console.print(
            Text(event.msg or fallback, style="bold green" if ok else "bold red")
        )
        if output := output_tail(data):
            console.print(Text(output, style="dim"))
    elif event.type == "recovery":
        message = event.msg or data.get("hypothesis", "Recovery attempt")
        console.print(Panel(Text(message), title="RECOVERY", border_style="yellow"))
        if not event.msg and data.get("next_cmd"):
            console.print(Text("Next: " + data["next_cmd"], style="yellow"))
    elif event.type in {"report_ready", "blocked"}:
        if event.type == "report_ready" and event.msg:
            console.print(Text(event.msg, style="bold green"))
        if event.type == "blocked":
            console.print(
                Text("BLOCKED: " + data.get("reason", event.msg), style="yellow")
            )
        markdown = data.get("quickstart_md", "")
        output = Path("out/QUICKSTART.md")
        output.parent.mkdir(exist_ok=True)
        output.write_text(markdown, encoding="utf-8")
        console.print(
            Panel(
                Markdown(markdown or "No verified report is available for this run."),
                title="Quickstart",
                border_style="green" if event.type == "report_ready" else "yellow",
            )
        )
        console.print(Text(f"Saved: {output.resolve()}"))
    elif event.type == "error":
        console.print(
            Text(
                event.msg or "ERROR: " + data.get("message", "Run failed"), style="red"
            )
        )
    else:
        message = event.msg or str(data.get("summary", data.get("name", event.type)))
        style = "bold green" if message.startswith("Verified:") else "dim"
        console.print(Text(message, style=style))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="FirstRun: a quickstart backed by actual setup attempts"
    )
    parser.add_argument("target", nargs="?")
    parser.add_argument(
        "--record",
        nargs="?",
        const="auto",
        metavar="PATH",
        help="save live events (default: timestamped runs file)",
    )
    parser.add_argument("--replay", metavar="PATH")
    parser.add_argument("--fast", action="store_true", help="skip replay delays")
    args = parser.parse_args(argv)
    if not args.replay and not args.target:
        parser.error("provide a target or --replay PATH")
    if args.replay and (args.target or args.record):
        parser.error("--replay cannot be combined with a target or --record")
    console = Console()
    console.print(
        Panel("FirstRun · verified repository onboarding", border_style="cyan")
    )
    terminal = None
    source = events = None
    try:
        if args.replay:
            console.print(
                Text(
                    f"REPLAY · {args.replay} · saved events; no commands executed",
                    style="bold yellow",
                )
            )
            source = replay(args.replay, fast=args.fast)
        else:
            from firstrun.agent import run

            source = run(args.target)
        events = source
        if args.record:
            path = (
                Path("runs") / (datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".jsonl")
                if args.record == "auto"
                else Path(args.record)
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            events = write_jsonl(str(path), source)
            console.print(Text(f"Recording: {path}"))
        try:
            for event in events:
                if terminal is not None:
                    raise ValueError("event stream continued after its terminal event")
                show(console, event)
                if event.type in TERMINAL:
                    terminal = event.type
            if terminal is None:
                raise ValueError("event stream ended without a terminal event")
        finally:
            events.close()
        return 0 if terminal == "report_ready" else 2 if terminal == "blocked" else 1
    except KeyboardInterrupt:
        console.print("Interrupted.")
        return 130
    except Exception as exc:  # noqa: BLE001 - terminal errors must remain readable without a traceback
        console.print(Text(f"ERROR: {exc}", style="red"))
        return 1
    finally:
        # Closing the recording tee does not close its source generator.
        if source is not None:
            source.close()
