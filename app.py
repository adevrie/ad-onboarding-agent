"""
app.py — Streamlit front end for the MOCKCO IT Workflow Orchestrator.

Wraps the existing OnboardingAgent (agent.py) in a chat-style UI with a
live "Agent Reasoning Trace" that streams the agent's logged reasoning
and tool calls while a request is being processed.

Run with:
    streamlit run app.py
"""

import logging
import os
import re
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

import streamlit as st

from agent import OnboardingAgent

# -----------------------------------------------------------------------
# Page config (must be the first Streamlit call)
# -----------------------------------------------------------------------
st.set_page_config(
    page_title="MOCKCO IT Workflow Orchestrator",
    layout="wide"
)

MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-4-8")
MAX_ITERATIONS = 20

EXAMPLE_REQUESTS = [
    "Onboard a new Process Engineer named Alex Rivera in Holland, starting 2026-06-23, manager is bmartinez",
    "Immediately offboard rwilson — security incident",
    "Onboard a new IT Admin named Jamie Torres in Grand Rapids",
    "What is the current status of Sandra Lopez?",
    "Offboard tpatel — voluntary resignation, last day June 20, delegate to cthompson",
]


# =============================================================================
# Logging handler — streams the agent's log records into a live placeholder
# =============================================================================

class StreamlitTraceHandler(logging.Handler):
    """
    Captures log records emitted by agent.py (reasoning, tool calls, results)
    and renders them into a Streamlit placeholder as they arrive, giving a
    live view of the agent's decision-making while run() is still executing.
    """

    _TOKEN_RE = re.compile(r"input_tokens=(\d+)\s+output_tokens=(\d+)")

    def __init__(self, placeholder):
        super().__init__()
        self.placeholder = placeholder
        self.lines: list[str] = []
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S"))

    def emit(self, record: logging.LogRecord):
        m = self._TOKEN_RE.search(record.getMessage())
        if m:
            self.total_input_tokens += int(m.group(1))
            self.total_output_tokens += int(m.group(2))
        self.lines.append(self.format(record))
        self.placeholder.code("\n".join(self.lines), language="text")


# =============================================================================
# Session state
# =============================================================================

def init_session_state():
    if "messages" not in st.session_state:
        st.session_state.messages = []  # [{"role": "user"|"assistant", "content": str}]
    if "agent" not in st.session_state:
        st.session_state.agent = None
    if "pending_request" not in st.session_state:
        st.session_state.pending_request = None
    if "total_input_tokens" not in st.session_state:
        st.session_state.total_input_tokens = 0
    if "total_output_tokens" not in st.session_state:
        st.session_state.total_output_tokens = 0


def get_agent() -> OnboardingAgent:
    if st.session_state.agent is None:
        try:
            st.session_state.agent = OnboardingAgent(model=MODEL, max_iterations=MAX_ITERATIONS)
        except Exception as e:
            st.error(
                f"**Failed to initialize the agent.**\n\n"
                f"```\n{type(e).__name__}: {e}\n```\n\n"
                f"Verify that your `ANTHROPIC_API_KEY` is valid and that the model name "
                f"(`{MODEL}`) is correct."
            )
            st.stop()
    return st.session_state.agent


# =============================================================================
# Transcript export
# =============================================================================

def format_transcript_as_markdown() -> str:
    lines = [
        "# MOCKCO IT Workflow Orchestrator — Transcript\n",
        f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
    ]
    for msg in st.session_state.messages:
        lines.append("\n---\n")
        if msg["role"] == "user":
            lines.append(f"### User\n\n{msg['content']}")
        else:
            lines.append(f"### Assistant\n\n{msg['content']}")
            trace = msg.get("trace")
            if trace:
                lines.append(f"\n**Reasoning Trace:**\n\n```\n{trace}\n```")
    return "\n".join(lines)


# =============================================================================
# Sidebar
# =============================================================================

def render_sidebar():
    with st.sidebar:
        st.title("MOCKCO IT Agent")
        st.markdown(f"**Model:** `{MODEL}`")
        st.markdown(f"**Max iterations:** {MAX_ITERATIONS}")

        st.divider()
        st.caption("Session Usage")
        col1, col2 = st.columns(2)
        col1.metric("Input tokens", f"{st.session_state.total_input_tokens:,}")
        col2.metric("Output tokens", f"{st.session_state.total_output_tokens:,}")

        st.divider()

        if st.button("New Conversation", use_container_width=True):
            if st.session_state.agent is not None:
                st.session_state.agent.reset()
            st.session_state.messages = []
            st.session_state.pending_request = None
            st.session_state.total_input_tokens = 0
            st.session_state.total_output_tokens = 0
            st.rerun()

        transcript_md = format_transcript_as_markdown()
        st.download_button(
            label="Download Transcript",
            data=transcript_md,
            file_name=f"mockco_transcript_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md",
            mime="text/markdown",
            use_container_width=True,
            disabled=len(st.session_state.messages) == 0,
        )

        st.divider()
        st.subheader("Example Requests")
        st.caption("Click to send a sample request to the agent.")
        for i, example in enumerate(EXAMPLE_REQUESTS):
            if st.button(example, key=f"example_btn_{i}", use_container_width=True):
                st.session_state.pending_request = example
                st.rerun()

        st.divider()
        with st.expander("Environment Reference", expanded=False):
            st.markdown("""
**Locations:** Holland · Grand Rapids (HQ) · Kalamazoo · Big Rapids

**License Tiers:**
| Tier | Typical Roles |
|---|---|
| E5 | IT Admins, General Managers, Executives |
| E3 | Engineers, HR, Sales Managers |
| F3 | Frontline / production workers, drivers |
| Business Premium | Purchasing, Production Control |

**Group Naming:**
- `SG-Department-Access` — security groups
- `SG-Role-Title` — role-based groups
- `DL-GroupName` — distribution lists
            """)


# =============================================================================
# Chat rendering + agent execution
# =============================================================================

def render_chat_history():
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            trace = msg.get("trace")
            if trace:
                with st.expander("Reasoning Trace"):
                    st.code(trace, language="text")
            st.markdown(msg["content"])


def run_agent_request(user_input: str):
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        with st.status("Agent Reasoning Trace", expanded=True) as status:
            trace_placeholder = st.empty()
            handler = StreamlitTraceHandler(trace_placeholder)
            agent_logger = logging.getLogger("onboarding-agent")
            agent_logger.addHandler(handler)

            try:
                agent = get_agent()
                response_text = agent.run(user_input)
                status.update(label="Agent Reasoning Trace — complete", state="complete")
            except Exception as e:
                status.update(label="Agent Reasoning Trace — error", state="error")
                response_text = (
                    "**The agent encountered an error while processing this request.**\n\n"
                    f"```\n{type(e).__name__}: {e}\n```"
                )
            finally:
                agent_logger.removeHandler(handler)
                st.session_state.total_input_tokens += handler.total_input_tokens
                st.session_state.total_output_tokens += handler.total_output_tokens

        st.markdown(response_text)

    st.session_state.messages.append({
        "role": "assistant",
        "content": response_text,
        "trace": "\n".join(handler.lines),
    })


# =============================================================================
# Main
# =============================================================================

def main():
    init_session_state()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        st.error(
            "**ANTHROPIC_API_KEY is not set.**\n\n"
            "To fix this:\n"
            "1. Copy `.env.example` to `.env` in the project root\n"
            "2. Add your key: `ANTHROPIC_API_KEY=sk-ant-...`\n"
            "3. Restart the app (`streamlit run app.py`)"
        )
        st.stop()

    render_sidebar()

    # Best-effort styling: right-align user chat bubbles, left-align assistant.
    # Relies on Streamlit's internal DOM structure (data-testid attributes) and
    # the CSS :has() selector — purely cosmetic, safe to remove if it breaks
    # on a future Streamlit version.
    st.markdown(
        """
        <style>
        [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {
            flex-direction: row-reverse;
            text-align: right;
        }
        [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) [data-testid="stChatMessageContent"] {
            text-align: right;
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    st.title("MOCKCO IT Workflow Orchestrator")
    st.caption("Agentic onboarding/offboarding automation powered by Claude + MCP-style tools")

    with st.expander("About this system", expanded=False):
        st.markdown("""
        This agent automates IT onboarding and offboarding for the MOCKCO
        hybrid enterprise environment. It uses Claude as a reasoning engine
        with 9 MCP-style tools that simulate Active Directory, Exchange,
        and Microsoft 365 operations.

        **The agent decides** which tools to call and in what order —
        no workflow steps are hardcoded in Python.

        **Environment:** MOCKCO (mockcompany.local) · 4 locations ·
        10 departments · Hybrid Exchange + M365

        **Try the example requests in the sidebar to see the agent work.**
        """)

    render_chat_history()

    # Example button clicks are processed as if the user typed and sent them
    if st.session_state.pending_request:
        prompt = st.session_state.pending_request
        st.session_state.pending_request = None
        run_agent_request(prompt)

    prompt = st.chat_input("Describe the onboarding/offboarding task...")
    if prompt:
        run_agent_request(prompt)


if __name__ == "__main__":
    main()
