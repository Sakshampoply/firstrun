"""Thin Streamlit frontend: events in, activity and report out."""
from pathlib import Path
import streamlit as st
from firstrun.events import Event, write_jsonl
from firstrun.replay import replay

ROOT = Path(__file__).resolve().parent.parent
st.set_page_config(page_title="FirstRun", page_icon="▶", layout="wide")
st.title("FirstRun")
st.caption("Your first successful run of an unfamiliar repo.")
st.info("Sandbox-lite · use pre-vetted Python repos. Live execution needs the Claude agent modules and an API connection.")


def render_report(event: Event) -> None:
    data = event.data
    report = data.get("report", {})
    if event.type == "blocked":
        st.warning("Blocked: " + data.get("reason", event.msg))
    st.subheader(report.get("name", "Quickstart"))
    st.write(report.get("summary", "No verified report yet. Agent implementation is pending."))
    if report.get("setup_steps"):
        st.markdown("**Setup evidence**")
        st.table(report["setup_steps"])
    verification = report.get("verification", {})
    if verification:
        st.markdown("**Verification**")
        st.write(f"{verification.get('status', 'untested')} · {verification.get('cmd', '')}")
        st.code(verification.get("evidence", "No execution evidence."), language="text")
    for obstacle in report.get("obstacles", []):
        st.write(("Resolved: " if obstacle.get("resolved") else "Unresolved: ") + obstacle.get("what", ""))
        st.caption(obstacle.get("workaround", ""))
    if report.get("read_first"):
        st.markdown("**Read first**")
        for item in report["read_first"]:
            st.text(f"{item.get('path', '')} — {item.get('why', '')}")
    if "elapsed_s" in report:
        st.caption(f"{report['elapsed_s']} seconds · {report.get('tool_calls', 0)} tool calls")
    markdown = data.get("quickstart_md", "")
    st.download_button("Download QUICKSTART.md", data=markdown, file_name="QUICKSTART.md", mime="text/markdown", disabled=not markdown)


def render_event(event: Event) -> None:
    data = event.data
    if event.type == "command_started":
        st.code("$ " + data.get("cmd", ""), language="bash")
    elif event.type == "command_finished":
        text = f"Exit {data.get('exit_code')} · {data.get('duration_s', 0):.2f}s"
        (st.success if data.get("exit_code") == 0 else st.error)(text)
        output = "\n".join(data.get(key, "").rstrip() for key in ("stdout_tail", "stderr_tail") if data.get(key))
        if output:
            st.code(output, language="text")
    elif event.type == "recovery":
        st.warning("Recovery: " + data.get("hypothesis", event.msg))
        if data.get("next_cmd"):
            st.caption("Next: " + data["next_cmd"])
    elif event.type == "error":
        st.error(data.get("message", event.msg))
    elif event.type not in {"report_ready", "blocked"}:
        st.write(event.msg or data.get("summary", data.get("name", event.type)))


mode = st.radio("Source", ["Live", "REPLAY"], horizontal=True)
target = st.text_input("Repository URL or local path", value="fixtures/stale-readme", disabled=mode == "REPLAY")
record = st.checkbox("Record live run to runs/fixture.jsonl", value=True, disabled=mode == "REPLAY")
recordings = sorted((ROOT / "runs").glob("*.jsonl"))
selected = st.selectbox("Replay a recorded run — REPLAY", recordings, format_func=lambda p: p.name, disabled=mode != "REPLAY")
fast = st.checkbox("Fast replay", value=False, disabled=mode != "REPLAY")
clicked = st.button("Run", type="primary", disabled=mode == "REPLAY" and not recordings)
if clicked:
    st.session_state["events"] = []
    st.session_state["source"] = "REPLAY" if mode == "REPLAY" else "LIVE"
    st.session_state["sample"] = mode == "REPLAY" and selected is not None and selected.name == "sample.jsonl"

if st.session_state.get("source") == "REPLAY":
    st.warning("REPLAY · saved events; no repository commands or API calls are being executed.")
    if st.session_state.get("sample"):
        st.caption("Illustrative sample assembled from fixture command checks; this is not a recorded agent run.")

activity, result = st.columns([1.1, 1], gap="large")
with activity:
    st.subheader("Activity")
    feed = st.container()
with result:
    st.subheader("Onboarding report")
    report_box = st.container()

def display(event):
    with feed:
        render_event(event)
    if event.type in {"report_ready", "blocked"}:
        with report_box:
            render_report(event)

if clicked:
    try:
        if mode == "REPLAY":
            events = replay(str(selected), fast=fast)
        else:
            if not target.strip():
                raise ValueError("Enter a repository URL or local path.")
            from firstrun.agent import run
            events = run(target.strip())
            if record:
                (ROOT / "runs").mkdir(exist_ok=True)
                events = write_jsonl(str(ROOT / "runs/fixture.jsonl"), events)
        terminal = None
        for event in events:
            if terminal is not None:
                raise ValueError("Event stream continued after its terminal event.")
            st.session_state["events"].append(event)
            display(event)
            if event.type in {"report_ready", "blocked", "error"}:
                terminal = event.type
        if terminal is None:
            raise ValueError("Event stream ended without a terminal event.")
    except Exception as exc:
        event = Event("error", data={"message": str(exc)})
        st.session_state["events"].append(event)
        display(event)
else:
    for event in st.session_state.get("events", []):
        display(event)
