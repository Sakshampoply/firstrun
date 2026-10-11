"""Streamlit frontend: events in, a live activity timeline and a verified quickstart out."""

import html
import re
from datetime import datetime
from pathlib import Path

import streamlit as st

from firstrun.events import Event, write_jsonl
from firstrun.replay import replay

ROOT = Path(__file__).resolve().parent.parent
TERMINAL = {"report_ready", "blocked", "error"}
TAIL_LINES = 6
CHIP = {"passed": ("pass", "✓"), "failed": ("fail", "✕"), "untested": ("idle", "○")}

CSS = """
<style>
:root {
  --bg: #09090b; --panel: #111114; --panel-2: #17171c; --line: #27272a;
  --text: #f4f4f5; --muted: #a1a1aa; --faint: #9a9aa5;
  --violet: #8b5cf6; --cyan: #22d3ee;
  --pass: #34d399; --pass-bg: rgba(52, 211, 153, .12);
  --fail: #fb7185; --fail-bg: rgba(251, 113, 133, .12);
  --warn: #fbbf24; --warn-bg: rgba(251, 191, 36, .12);
  --mono: 'JetBrains Mono', 'SF Mono', Menlo, Consolas, monospace;
}
.stApp {
  background:
    radial-gradient(1100px 520px at 0% -10%, rgba(139, 92, 246, .20), transparent 60%),
    radial-gradient(900px 480px at 100% -5%, rgba(34, 211, 238, .10), transparent 60%),
    var(--bg);
}
header[data-testid="stHeader"] { background: transparent; }
#MainMenu, footer, [data-testid="stToolbar"] { display: none; }
.block-container { padding-top: 1.1rem; max-width: 1440px; }

.fr-hero { display: flex; align-items: flex-end; justify-content: space-between; gap: 1rem; margin-bottom: .4rem; }
.fr-brand { display: flex; align-items: center; gap: .8rem; }
.fr-logo { width: 38px; height: 38px; border-radius: 12px; display: grid; place-items: center; font-size: 1.3rem;
  color: white; background: linear-gradient(135deg, var(--violet), var(--cyan));
  box-shadow: 0 10px 40px rgba(139, 92, 246, .45); }
.fr-word { font-size: 2.15rem; font-weight: 800; letter-spacing: -.04em; line-height: 1;
  background: linear-gradient(90deg, #fff 30%, #c4b5fd 70%, var(--cyan));
  -webkit-background-clip: text; background-clip: text; color: transparent; }
.fr-hero p.fr-tag { color: var(--muted); font-size: 1.05rem; margin: .3rem 0 0; }
.fr-mode { font: 600 .85rem/1 var(--mono); letter-spacing: .12em; padding: .55rem .8rem; border-radius: 999px;
  border: 1px solid var(--line); background: var(--panel); position: fixed; top: 1rem; right: 1.5rem; z-index: 1001; }
.fr-mode.live { color: var(--pass); } .fr-mode.replay { color: var(--warn); border-color: rgba(251, 191, 36, .45); }

.fr-banner { border-radius: 14px; padding: .9rem 1.1rem; margin: .4rem 0 .2rem; font-size: 1.05rem;
  border: 1px solid; display: flex; gap: .7rem; align-items: baseline; }
.fr-banner b { font-family: var(--mono); letter-spacing: .1em; }
.fr-banner.replay { color: var(--warn); background: var(--warn-bg); border-color: rgba(251, 191, 36, .35); }
.fr-banner.blocked { color: var(--warn); background: var(--warn-bg); border-color: rgba(251, 191, 36, .35); }
.fr-banner.error { color: var(--fail); background: var(--fail-bg); border-color: rgba(251, 113, 133, .35); }

.fr-stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: .8rem; margin: .5rem 0 1rem; }
.fr-stat { background: linear-gradient(180deg, var(--panel-2), var(--panel)); border: 1px solid var(--line);
  border-radius: 16px; padding: .7rem 1rem; }
.fr-stat .k { color: var(--faint); font-size: .8rem; text-transform: uppercase; letter-spacing: .14em; }
.fr-stat .v { font-size: 1.65rem; font-weight: 750; letter-spacing: -.02em; margin-top: .25rem; }
.fr-stat .s { color: var(--muted); font-size: .95rem; }
.fr-stat.pass .v { color: var(--pass); } .fr-stat.fail .v { color: var(--fail); }
.fr-stat.warn .v { color: var(--warn); } .fr-stat.run .v { color: #c4b5fd; }
.fr-pulse { display: inline-block; width: .7rem; height: .7rem; border-radius: 50%; background: var(--violet);
  margin-right: .5rem; animation: fr-pulse 1.2s ease-in-out infinite; vertical-align: middle; }
@keyframes fr-pulse { 0%, 100% { opacity: .35; transform: scale(.85); } 50% { opacity: 1; transform: scale(1.1); } }

.fr-h { font-size: .85rem; color: var(--faint); text-transform: uppercase; letter-spacing: .16em;
  font-weight: 600; margin: 0 0 .7rem; }

.st-key-feed { border-left: 2px solid var(--line); padding-left: 1.3rem; margin-left: .45rem; }
.st-key-feed [data-testid="stVerticalBlock"] { gap: .45rem; }
.fr-ev { position: relative; font-size: 1.08rem; line-height: 1.5; color: var(--text); }
.fr-ev::before { content: ""; position: absolute; left: calc(-1.3rem - 7px); top: .55em; width: 12px; height: 12px;
  border-radius: 50%; background: var(--bg); border: 2px solid var(--faint); }
.fr-ev.status { color: var(--muted); }
.fr-ev.tool { color: var(--faint); font-size: 1rem; }
.fr-ev.tool::before { width: 8px; height: 8px; left: calc(-1.3rem - 5px); border-color: var(--line); background: var(--line); }
.fr-ev.cmd::before { border-color: #c4b5fd; }
.fr-ev.pass::before, .fr-ev.verified::before { border-color: var(--pass); background: var(--pass); }
.fr-ev.fail::before { border-color: var(--fail); background: var(--fail); }
.fr-ev.recovery::before { border-color: var(--warn); background: var(--warn); }
.fr-cmdline { font-family: var(--mono); font-size: 1.02rem; background: var(--panel); border: 1px solid var(--line);
  border-radius: 12px; padding: .65rem .9rem; color: #ede9fe; word-break: break-word; }
.fr-cmdline .p { color: var(--violet); margin-right: .6rem; font-weight: 700; }
.fr-result { display: flex; gap: .7rem; align-items: baseline; flex-wrap: wrap; }
.fr-result .msg { word-break: break-word; }
.fr-badge { font: 700 .78rem/1 var(--mono); letter-spacing: .08em; padding: .35rem .55rem; border-radius: 8px; white-space: nowrap; }
.fr-badge.pass { color: var(--pass); background: var(--pass-bg); }
.fr-badge.fail { color: var(--fail); background: var(--fail-bg); }
.fr-tail { font: .88rem/1.5 var(--mono); color: var(--muted); background: #0c0c0f; border: 1px solid var(--line);
  border-radius: 10px; padding: .6rem .8rem; margin: .45rem 0 0; word-break: break-word; }
.fr-card { border-radius: 14px; padding: .85rem 1rem; border: 1px solid; }
.fr-card.recovery { background: var(--warn-bg); border-color: rgba(251, 191, 36, .35); }
.fr-card .label { color: var(--warn); font: 700 .78rem/1 var(--mono); letter-spacing: .14em; text-transform: uppercase; }
.fr-card .hyp { font-size: 1.12rem; margin: .45rem 0 .35rem; }
.fr-card .next { font-family: var(--mono); color: var(--warn); }
.fr-card.verified { background: var(--pass-bg); border-color: rgba(52, 211, 153, .4); color: var(--pass);
  font-size: 1.18rem; font-weight: 650; }
.fr-ev code, .fr-report code, .fr-card code { font-family: var(--mono); font-size: .92em; color: #ede9fe;
  background: rgba(139, 92, 246, .14); padding: .08em .38em; border-radius: 6px; }

.fr-empty { border: 1px dashed var(--line); border-radius: 18px; padding: 2.2rem 1.6rem; color: var(--faint);
  text-align: center; font-size: 1.05rem; background: rgba(17, 17, 20, .55); }
.fr-empty b { color: var(--muted); display: block; font-size: 1.2rem; margin-bottom: .3rem; }

.fr-report { background: linear-gradient(180deg, var(--panel-2), var(--panel)); border: 1px solid var(--line);
  border-radius: 20px; padding: 1.5rem 1.6rem; }
.fr-rhead { display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem; }
.fr-eyebrow { color: var(--faint); font: 600 .8rem var(--mono); letter-spacing: .14em; }
.fr-rhead h2 { margin: .2rem 0 0; font-size: 2rem; letter-spacing: -.03em; padding: 0; }
.fr-summary { color: var(--muted); font-size: 1.08rem; margin: .7rem 0 0; }
.fr-report h4 { color: var(--faint); font-size: .8rem; text-transform: uppercase; letter-spacing: .16em;
  margin: 1.4rem 0 .6rem; padding: 0; }
.fr-report ol, .fr-report ul { list-style: none; margin: 0; padding: 0; }
.fr-report li { display: flex; gap: .75rem; align-items: baseline; padding: .5rem 0;
  border-bottom: 1px solid rgba(39, 39, 42, .7); font-size: 1.05rem; flex-wrap: wrap; }
.fr-report li:last-child { border-bottom: 0; }
.fr-note { color: var(--faint); font-size: .95rem; }
.fr-chip { font: 700 .76rem/1 var(--mono); letter-spacing: .06em; padding: .38rem .55rem; border-radius: 999px;
  white-space: nowrap; text-transform: uppercase; }
.fr-chip.pass { color: var(--pass); background: var(--pass-bg); }
.fr-chip.fail { color: var(--fail); background: var(--fail-bg); }
.fr-chip.idle { color: var(--muted); background: rgba(161, 161, 170, .12); }
.fr-chip.big { font-size: .9rem; padding: .55rem .8rem; }
.fr-evidence { display: flex; gap: .7rem; align-items: baseline; flex-wrap: wrap; font-size: 1.05rem; }
.fr-evidence .arrow { color: var(--faint); }
.fr-report li.fr-gotcha { flex-wrap: nowrap; }
.fr-gotcha .ico { color: var(--warn); font-weight: 800; }
.fr-meta { color: var(--faint); font: .88rem var(--mono); margin-top: 1.3rem; overflow-wrap: anywhere; }

[data-testid="stTextInputRootElement"] { height: 3.1rem; border-radius: 12px; background: var(--panel); }
[data-testid="stTextInputRootElement"] input { font-family: var(--mono); font-size: 1.05rem; }
div[data-baseweb="select"] > div { border-radius: 12px; background: var(--panel); min-height: 3.1rem; font-family: var(--mono); }
button[data-testid="stBaseButton-primary"] { height: 3.1rem; border: 0; border-radius: 12px; font-weight: 700;
  font-size: 1.08rem; background: linear-gradient(135deg, var(--violet), #6366f1);
  box-shadow: 0 10px 34px rgba(139, 92, 246, .38); }
button[data-testid="stBaseButton-primary"]:hover { filter: brightness(1.12); }
[data-testid="stDownloadButton"] button { height: 3rem; border-radius: 12px; font-weight: 650;
  border: 1px solid rgba(139, 92, 246, .55); background: rgba(139, 92, 246, .12); color: #ede9fe; }
</style>
"""


def esc(text: object) -> str:
    return html.escape(str(text))


def rich(text: object) -> str:
    """Escape model text, then turn `backticks` into inline code."""
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", esc(text))


def output_tail(data: dict) -> str:
    output = "\n".join(
        data.get(key, "").rstrip()
        for key in ("stdout_tail", "stderr_tail")
        if data.get(key)
    )
    return "\n".join(output.splitlines()[-TAIL_LINES:])


def chip(status: str, big: bool = False) -> str:
    kind, mark = CHIP.get(status, CHIP["untested"])
    label = {"passed": "verified"}.get(status, status) if big else status
    return f'<span class="fr-chip {kind}{" big" if big else ""}">{mark} {esc(label)}</span>'


def event_html(event: Event) -> str:
    data = event.data
    if event.type == "command_started":
        cmd = esc(data.get("cmd", ""))
        return f'<div class="fr-ev cmd"><div class="fr-cmdline"><span class="p">$</span>{cmd}</div></div>'
    if event.type == "command_finished":
        ok = data.get("exit_code") == 0
        kind = "pass" if ok else "fail"
        duration = f"{float(data.get('duration_s', 0)):.2f}s"
        badge = (
            f"PASS · {duration}"
            if ok
            else f"FAIL · EXIT {data.get('exit_code')} · {duration}"
        )
        # The command is on the line above, so keep only what the badge does not say.
        detail = "" if ok else re.sub(r"^Failed \(exit -?\d+\): ", "", event.msg)
        tail = "<br>".join(esc(line) for line in output_tail(data).splitlines())
        return (
            f'<div class="fr-ev {kind}"><div class="fr-result"><span class="fr-badge {kind}">{badge}</span>'
            f'<span class="msg">{rich(detail)}</span></div>'
            + (f'<div class="fr-tail">{tail}</div>' if tail else "")
            + "</div>"
        )
    if event.type == "recovery":
        attempt = data.get("attempt", 1)
        hypothesis = data.get("hypothesis") or event.msg
        nxt = data.get("next_cmd", "")
        return (
            f'<div class="fr-ev recovery"><div class="fr-card recovery">'
            f'<div class="label">Recovery · attempt {esc(attempt)}</div>'
            f'<div class="hyp">{rich(hypothesis)}</div>'
            + (f'<div class="next">→ {esc(nxt)}</div>' if nxt else "")
            + "</div></div>"
        )
    if event.type in {"tool_call", "tool_result"}:
        message = event.msg or data.get("summary", data.get("name", event.type))
        return f'<div class="fr-ev tool">{esc(message)}</div>'
    if event.type == "report_ready":
        return '<div class="fr-ev pass">Quickstart ready</div>'
    if event.type == "blocked":
        return f'<div class="fr-ev fail">Blocked: {esc(data.get("reason", event.msg))}</div>'
    if event.type == "error":
        return f'<div class="fr-ev fail">{esc(event.msg or data.get("message", "Error"))}</div>'
    message = event.msg or data.get("summary", event.type)
    message = message.replace(str(ROOT) + "/", "")
    if message.startswith("Verified:"):
        return f'<div class="fr-ev verified"><div class="fr-card verified">✓ {esc(message)}</div></div>'
    return f'<div class="fr-ev status">{esc(message)}</div>'


def stats_html(events: list[Event], running: bool) -> str:
    finished = [e for e in events if e.type == "command_finished"]
    failed = sum(1 for e in finished if e.data.get("exit_code") != 0)
    recoveries = sum(1 for e in events if e.type == "recovery")
    terminal = next((e for e in reversed(events) if e.type in TERMINAL), None)
    report = terminal.data.get("report", {}) if terminal else {}
    elapsed = report.get("elapsed_s") or (events[-1].ts - events[0].ts if events else 0)
    calls = report.get("tool_calls")

    if running:
        outcome = ("run", '<span class="fr-pulse"></span>Running', "agent at work")
    elif terminal is None and events:
        outcome = ("warn", "Interrupted", "a control was touched; run again")
    elif terminal is None:
        outcome = ("", "Ready", "paste a repo and run")
    elif terminal.type == "report_ready":
        verified = report.get("verification", {}).get("status") == "passed"
        outcome = (
            ("pass", "Verified", "quickstart tested")
            if verified
            else ("warn", "Not verified", "see report")
        )
    elif terminal.type == "blocked":
        outcome = ("warn", "Blocked", "partial report")
    else:
        outcome = ("fail", "Error", "see activity")

    tiles = [
        (outcome[0], "Outcome", outcome[1], outcome[2]),
        ("fail" if failed else "", "Commands", str(len(finished)), f"{failed} failed"),
        (
            "warn" if recoveries else "",
            "Recoveries",
            str(recoveries),
            "hypothesis → retry",
        ),
        (
            "",
            "Time",
            f"{elapsed:.1f}s",
            f"{calls} tool calls" if calls is not None else "wall clock",
        ),
    ]
    cells = "".join(
        f'<div class="fr-stat {kind}"><div class="k">{key}</div><div class="v">{value}</div>'
        f'<div class="s">{esc(sub)}</div></div>'
        for kind, key, value, sub in tiles
    )
    return f'<div class="fr-stats">{cells}</div>'


def report_html(report: dict) -> str:
    check = report.get("verification", {})
    steps = "".join(
        f"<li>{chip(s.get('status', 'untested'))}<code>{esc(s.get('cmd', ''))}</code>"
        + (f'<span class="fr-note">{rich(s["note"])}</span>' if s.get("note") else "")
        + "</li>"
        for s in report.get("setup_steps", [])
    )
    evidence = (check.get("evidence") or "").strip().splitlines()
    verify = (
        f'<div class="fr-evidence">{chip(check.get("status", "untested"))}'
        f"<code>{esc(check['cmd'])}</code>"
        + (
            f'<span class="arrow">→</span><code>{esc(evidence[-1])}</code>'
            if evidence
            else ""
        )
        + "</div>"
        if check.get("cmd")
        else '<div class="fr-note">No verification command ran.</div>'
    )
    gotchas = (
        "".join(
            f'<li class="fr-gotcha"><span class="ico">!</span><span>{rich(o.get("what", ""))}'
            + (
                f'<br><span class="fr-note">Fix: {rich(o["workaround"])}</span>'
                if o.get("workaround")
                else ""
            )
            + "</span></li>"
            for o in report.get("obstacles", [])
        )
        or '<li class="fr-note">None recorded.</li>'
    )
    read_first = (
        "".join(
            f'<li><code>{esc(r.get("path", ""))}</code><span class="fr-note">{rich(r.get("why", ""))}</span></li>'
            for r in report.get("read_first", [])
        )
        or '<li class="fr-note">Nothing flagged.</li>'
    )
    meta = " · ".join(
        part
        for part in (
            esc(str(report.get("target", "")).replace(str(ROOT) + "/", "")),
            f"{report['elapsed_s']}s" if "elapsed_s" in report else "",
            f"{report['tool_calls']} tool calls" if "tool_calls" in report else "",
        )
        if part
    )
    return (
        '<div class="fr-report"><div class="fr-rhead"><div><div class="fr-eyebrow">QUICKSTART.md</div>'
        f"<h2>{esc(report.get('name', 'Quickstart'))}</h2></div>{chip(check.get('status', 'untested'), big=True)}</div>"
        f'<p class="fr-summary">{rich(report.get("summary", ""))}</p>'
        f"<h4>Setup</h4><ol>{steps or '<li class=fr-note>No setup commands ran.</li>'}</ol>"
        f"<h4>Verify</h4>{verify}<h4>Gotchas</h4><ul>{gotchas}</ul>"
        f'<h4>Read first</h4><ul>{read_first}</ul><div class="fr-meta">{meta}</div></div>'
    )


def render_result(event: Event) -> None:
    data = event.data
    if event.type == "error":
        message = data.get("message", event.msg) or "Run failed"
        st.markdown(
            f'<div class="fr-banner error"><b>ERROR</b>{esc(message)}</div>',
            unsafe_allow_html=True,
        )
        return
    if event.type == "blocked":
        reason = data.get("reason", event.msg)
        st.markdown(
            f'<div class="fr-banner blocked"><b>BLOCKED</b>{esc(reason)}</div>',
            unsafe_allow_html=True,
        )
    markdown = data.get("quickstart_md", "")
    report_tab, file_tab = st.tabs(["Report", "QUICKSTART.md"])
    with report_tab:
        st.markdown(report_html(data.get("report", {})), unsafe_allow_html=True)
    with file_tab:
        st.code(markdown or "No report for this run.", language="markdown")
    st.download_button(
        "⬇  Download QUICKSTART.md",
        data=markdown,
        file_name="QUICKSTART.md",
        mime="text/markdown",
        disabled=not markdown,
        on_click="ignore",
        use_container_width=True,
    )


def empty(title: str, hint: str) -> str:
    return f'<div class="fr-empty"><b>{esc(title)}</b>{esc(hint)}</div>'


st.set_page_config(
    page_title="FirstRun",
    page_icon="▶",
    layout="wide",
    initial_sidebar_state="collapsed",
)
st.markdown(CSS, unsafe_allow_html=True)

mode = st.session_state.get("mode", "Live")
replaying = st.session_state.get("source") == "REPLAY"
st.markdown(
    '<div class="fr-hero"><div><div class="fr-brand"><div class="fr-logo">▶</div>'
    '<div class="fr-word">FirstRun</div></div>'
    '<p class="fr-tag">Paste a repo. Get a quickstart the agent actually ran.</p></div></div>',
    unsafe_allow_html=True,
)

source_col, target_col, run_col = st.columns([1.6, 5, 1.3], vertical_alignment="bottom")
with source_col:
    mode = (
        st.segmented_control("Source", ["Live", "Replay"], key="mode", default="Live")
        or "Live"
    )
recordings = sorted((ROOT / "runs").glob("*.jsonl"))
with target_col:
    if mode == "Live":
        target = st.text_input(
            "Repository URL or local path", value="fixtures/stale-readme"
        )
        selected = None
    else:
        target = ""
        selected = st.selectbox(
            "Saved run · REPLAY", recordings, format_func=lambda p: p.name
        )
with run_col:
    clicked = st.button(
        "Run  ▶" if mode == "Live" else "Replay  ▶",
        type="primary",
        use_container_width=True,
        disabled=mode == "Replay" and not recordings,
    )
if mode == "Live":
    record = st.toggle("Record this run", value=True)
    fast = False
else:
    fast = st.toggle("Fast replay", value=False)
    record = False

if clicked:
    st.session_state["events"] = []
    st.session_state["source"] = "REPLAY" if mode == "Replay" else "Live"
    st.session_state["replay_name"] = selected.name if selected else ""
    st.session_state["recording"] = None
    replaying = mode == "Replay"

# The pill labels the result on screen, not the toggle, so a replay never reads LIVE (D7).
shown_replay = (
    replaying if clicked or st.session_state.get("events") else mode == "Replay"
)
st.markdown(
    '<div class="fr-mode replay">● REPLAY</div>'
    if shown_replay
    else '<div class="fr-mode live">● LIVE</div>',
    unsafe_allow_html=True,
)

if replaying:
    name = st.session_state.get("replay_name", "")
    note = (
        "Illustrative sample: fixture command checks with scripted timing."
        if name == "sample.jsonl"
        else "Saved events from a real run. No commands or API calls are executed."
    )
    st.markdown(
        f'<div class="fr-banner replay"><b>REPLAY</b>{esc(name)} · {esc(note)}</div>',
        unsafe_allow_html=True,
    )

stats_slot = st.empty()
if clicked:
    stats_slot.markdown(stats_html([], running=True), unsafe_allow_html=True)
activity, result = st.columns([1, 1.1], gap="large")
with activity:
    st.markdown('<div class="fr-h">Activity</div>', unsafe_allow_html=True)
    feed = st.container(key="feed")
with result:
    st.markdown('<div class="fr-h">Quickstart</div>', unsafe_allow_html=True)
    report_box = st.container()


def display(event: Event) -> None:
    with feed:
        st.markdown(event_html(event), unsafe_allow_html=True)
    if event.type in TERMINAL:
        with report_box:
            render_result(event)


if clicked:
    with report_box:
        waiting = st.empty()
        waiting.markdown(
            empty("Working…", "The quickstart appears once the agent has verified it."),
            unsafe_allow_html=True,
        )
    source = events = None
    try:
        if mode == "Replay":
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
                if event.type in TERMINAL:
                    terminal = event.type
                    waiting.empty()
                display(event)
                stats_slot.markdown(
                    stats_html(st.session_state["events"], running=terminal is None),
                    unsafe_allow_html=True,
                )
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
    waiting.empty()
    stats_slot.markdown(
        stats_html(st.session_state["events"], running=False), unsafe_allow_html=True
    )
elif st.session_state.get("events"):
    for event in st.session_state["events"]:
        display(event)
    stats_slot.markdown(
        stats_html(st.session_state["events"], running=False), unsafe_allow_html=True
    )
else:
    stats_slot.markdown(stats_html([], running=False), unsafe_allow_html=True)
    with feed:
        st.markdown(
            empty("No run yet", "Try the hero fixture: fixtures/stale-readme"),
            unsafe_allow_html=True,
        )
    with report_box:
        st.markdown(
            empty(
                "Your QUICKSTART.md lands here",
                "Every step marked passed, failed or untested.",
            ),
            unsafe_allow_html=True,
        )

if recording := st.session_state.get("recording"):
    st.caption(f"Recorded: {recording}")
