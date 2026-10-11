"""Thin Streamlit frontend: events in, readable activity and quickstart out."""

import re
from datetime import datetime
from pathlib import Path

import streamlit as st

from firstrun.events import Event, write_jsonl
from firstrun.replay import replay

ROOT = Path(__file__).resolve().parent.parent
TERMINAL = {"report_ready", "blocked", "error"}
STATUS_ICONS = {"passed": "✅", "failed": "❌", "untested": "⚪"}

st.set_page_config(page_title="FirstRun", page_icon="▶", layout="wide")
st.markdown(
    """<style>
    [data-testid="stText"] {font-size: 1.25rem; line-height: 1.55;}
    [data-testid="stMarkdownContainer"] p {font-size: 1.15rem;}
    [data-testid="stCode"] pre {font-size: 1.05rem;}
    [data-testid="stCaptionContainer"] p {font-size: .95rem;}
    </style>""",
    unsafe_allow_html=True,
)
st.title("FirstRun")
st.caption("Paste a repo, get a quickstart the agent has actually tested.")


def escaped(message: str) -> str:
    """Keep filenames and tool output literal in Markdown-based callouts."""
    return re.sub(r"([\\`*_{}\[\]()<>#+!|~])", r"\\\1", message)


def output_tail(data: dict) -> str:
    output = "\n".join(
        data.get(key, "").rstrip()
        for key in ("stdout_tail", "stderr_tail")
        if data.get(key)
    )
    return "\n".join(output.splitlines()[-6:])


def render_report(event: Event) -> None:
    data = event.data
    if event.type == "error":
        st.error(escaped(event.msg or data.get("message", "Run failed")))
        return
    if event.type == "blocked":
        st.warning(escaped("Blocked: " + data.get("reason", event.msg)))
    markdown = data.get("quickstart_md", "")
    if markdown:
        st.markdown(markdown)
    else:
        st.text("No verified report is available for this run.")
    st.download_button(
        "Download QUICKSTART.md",
        data=markdown,
        file_name="QUICKSTART.md",
        mime="text/markdown",
        disabled=not markdown,
        on_click="ignore",
        use_container_width=True,
    )
    steps = data.get("report", {}).get("setup_steps", [])
    if steps:
        st.caption("Setup evidence")
        st.table(
            [
                {
                    "Status": STATUS_ICONS.get(step.get("status"), "⚪"),
                    "Command": step.get("cmd", ""),
                }
                for step in steps
            ]
        )


def render_event(event: Event) -> None:
    data = event.data
    if event.type == "command_started":
        st.code("$ " + data.get("cmd", ""), language="bash")
    elif event.type == "command_finished":
        ok = data.get("exit_code") == 0
        fallback = (
            f"{'Passed' if ok else 'Failed'} (exit {data.get('exit_code')}): "
            f"{data.get('cmd', '')}"
        )
        (st.success if ok else st.error)(escaped(event.msg or fallback))
        if output := output_tail(data):
            st.code(output, language="text")
    elif event.type == "recovery":
        message = event.msg or data.get("hypothesis", "Recovery attempt")
        st.warning(escaped(message))
        if not event.msg and data.get("next_cmd"):
            st.caption(escaped("Next: " + data["next_cmd"]))
    elif event.type in {"tool_call", "tool_result"}:
        message = event.msg or data.get("summary", data.get("name", event.type))
        st.caption(escaped(str(message)))
    elif event.type not in TERMINAL:
        message = event.msg or data.get("summary", event.type)
        if message.startswith("Verified:"):
            st.success(escaped(message))
        else:
            st.text(message)


with st.sidebar:
    st.subheader("Run source")
    mode = st.radio("Source", ["Live", "REPLAY"], horizontal=True)
    recordings = sorted((ROOT / "runs").glob("*.jsonl"))
    selected = st.selectbox(
        "REPLAY — saved runs",
        recordings,
        format_func=lambda p: p.name,
        disabled=mode != "REPLAY",
    )
    fast = st.checkbox("Fast replay", value=False, disabled=mode != "REPLAY")
    record = st.checkbox("Record live run", value=True, disabled=mode == "REPLAY")
    st.caption("Sandbox-lite · pre-vetted Python repos")

input_column, button_column = st.columns([5, 1], vertical_alignment="bottom")
with input_column:
    target = st.text_input(
        "Repository URL or local path",
        value="fixtures/stale-readme",
        disabled=mode == "REPLAY",
    )
with button_column:
    clicked = st.button(
        "Run",
        type="primary",
        use_container_width=True,
        disabled=mode == "REPLAY" and not recordings,
    )

if clicked:
    st.session_state["events"] = []
    st.session_state["source"] = mode
    st.session_state["sample"] = (
        mode == "REPLAY" and selected is not None and selected.name == "sample.jsonl"
    )
    st.session_state["recording"] = None

if st.session_state.get("source") == "REPLAY":
    st.warning("REPLAY · saved events; no commands or API calls are executed.")
    if st.session_state.get("sample"):
        st.caption(
            "Illustrative fixture sample; command checks, scripted event timing."
        )

activity, result = st.columns([1, 1.2], gap="large")
with activity:
    st.subheader("Activity")
    feed = st.container()
with result:
    st.subheader("Quickstart")
    report_box = st.container()


def display(event: Event) -> None:
    with feed:
        render_event(event)
    if event.type in TERMINAL:
        with report_box:
            render_report(event)


if clicked:
    source = events = None
    try:
        if mode == "REPLAY":
            source = replay(str(selected), fast=fast)
        else:
            if not target.strip():
                raise ValueError("Enter a repository URL or local path.")
            from firstrun.agent import run

            # Resolve local targets from the project, even if Streamlit starts elsewhere.
            resolved = target.strip()
            if not resolved.startswith("https://github.com/"):
                path = Path(resolved).expanduser()
                if not path.is_absolute():
                    path = ROOT / path
                resolved = str(path)
            source = run(resolved)
        events = source
        if mode == "Live" and record:
            runs_dir = ROOT / "runs"
            runs_dir.mkdir(exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            recording = runs_dir / f"live-{stamp}.jsonl"
            # Preserve earlier attempts even when two runs start in the same second.
            suffix = 1
            while recording.exists():
                recording = runs_dir / f"live-{stamp}-{suffix}.jsonl"
                suffix += 1
            st.session_state["recording"] = str(recording.relative_to(ROOT))
            events = write_jsonl(str(recording), source)
        try:
            terminal = None
            for event in events:
                if terminal is not None:
                    raise ValueError("Event stream continued after its terminal event.")
                st.session_state["events"].append(event)
                display(event)
                if event.type in TERMINAL:
                    terminal = event.type
            if terminal is None:
                raise ValueError("Event stream ended without a terminal event.")
        finally:
            events.close()
    except Exception as exc:  # noqa: BLE001 - surface run failures without crashing the demo UI
        event = Event("error", f"Error: {exc}", {"message": str(exc)})
        st.session_state["events"].append(event)
        display(event)
    finally:
        # The frozen recording tee does not propagate close to the agent generator.
        if source is not None:
            source.close()
else:
    for event in st.session_state.get("events", []):
        display(event)

if recording := st.session_state.get("recording"):
    st.caption(escaped("Recorded: " + recording))
