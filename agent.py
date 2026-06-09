"""
agent.py — Agentic loop for the IT Onboarding/Offboarding Workflow Orchestrator.

The LLM (Claude) drives all workflow decisions. This module provides the
execution infrastructure: call the model, execute the tools it requests,
feed results back, and repeat until the task is complete.

No workflow steps are hardcoded here. The model reads tool descriptions and
reasons about what to call and in what order.
"""

import json
import logging
import os
from datetime import datetime

import anthropic

from prompts import SYSTEM_PROMPT
from tools import TOOL_DEFINITIONS, execute_tool

# ---------------------------------------------------------------------------
# Logging — structured output that shows the agent's reasoning trace
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("onboarding-agent")


class OnboardingAgent:
    """
    Agentic IT workflow orchestrator backed by Claude.

    All workflow logic lives in the model — this class only:
      1. Maintains conversation history
      2. Calls the Anthropic API
      3. Executes tool calls the model requests
      4. Loops until the model signals end_turn
    """

    def __init__(
        self,
        model: str = "claude-opus-4-8",
        max_iterations: int = 20
    ):
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "ANTHROPIC_API_KEY environment variable not set. "
                "Copy .env.example to .env and add your key."
            )
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.max_iterations = max_iterations
        self.history: list[dict] = []
        log.info("Agent initialized  model=%s  max_iter=%d", model, max_iterations)

    # -----------------------------------------------------------------------
    # Public interface
    # -----------------------------------------------------------------------

    def run(self, user_request: str) -> str:
        """
        Process an onboarding or offboarding request end-to-end.

        Returns the model's final natural-language summary of what was done.
        """
        self._log_section(f"NEW REQUEST: {user_request[:120]}")

        self.history = [{"role": "user", "content": user_request}]

        for turn in range(1, self.max_iterations + 1):
            log.info("─── Agent Turn %d ───", turn)

            # ------------------------------------------------------------------
            # MODEL CALL — Claude decides what to do next.
            # It may: call tools, ask a clarifying question, or declare done.
            # ------------------------------------------------------------------
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=TOOL_DEFINITIONS,
                messages=self.history,
                thinking={"type": "adaptive"}
            )

            log.info(
                "Model responded  stop_reason=%s  blocks=%d  input_tokens=%d  output_tokens=%d",
                response.stop_reason,
                len(response.content),
                response.usage.input_tokens,
                response.usage.output_tokens
            )

            # Append assistant turn to history (must include the raw content list)
            self.history.append({"role": "assistant", "content": response.content})

            # Log any visible reasoning text the model emitted
            for block in response.content:
                if getattr(block, "type", None) == "text" and block.text.strip():
                    preview = block.text[:400].replace("\n", " ")
                    log.info("[AGENT REASONING] %s%s", preview, "…" if len(block.text) > 400 else "")

            # ------------------------------------------------------------------
            # TASK COMPLETE — model decided it has nothing more to do
            # ------------------------------------------------------------------
            if response.stop_reason == "end_turn":
                log.info("end_turn reached — workflow complete")
                return self._extract_text(response.content)

            # ------------------------------------------------------------------
            # TOOL EXECUTION — model wants to call one or more tools
            # ------------------------------------------------------------------
            if response.stop_reason == "tool_use":
                tool_blocks = [
                    b for b in response.content
                    if getattr(b, "type", None) == "tool_use"
                ]
                log.info("Model requested %d tool call(s)", len(tool_blocks))

                tool_results = []
                for block in tool_blocks:
                    result_json = self._execute_and_log(block.name, block.input, block.id)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_json
                    })

                # Return all results to the model in a single user turn
                self.history.append({"role": "user", "content": tool_results})
                continue

            # Unexpected stop reason — log and break
            log.warning("Unexpected stop_reason: %s — ending loop", response.stop_reason)
            return self._extract_text(response.content)

        # Hit the iteration ceiling
        log.warning("Max iterations (%d) reached — workflow may be incomplete", self.max_iterations)
        return (
            "The workflow reached the maximum iteration limit and may be incomplete. "
            "Please review the logged actions above and finish any remaining steps manually."
        )

    def get_history(self) -> list[dict]:
        """Return full conversation history (for debugging or display)."""
        return self.history

    def reset(self):
        """Clear conversation history to start a fresh request."""
        self.history = []
        log.info("Conversation history cleared")

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    def _execute_and_log(self, tool_name: str, tool_input: dict, tool_id: str) -> str:
        """Execute a single tool call and log the outcome. Returns raw JSON string."""
        log.info(
            ">> TOOL CALL  name=%s  id=%s",
            tool_name,
            tool_id[:12]
        )
        # Log inputs on separate line, truncated to keep the trace readable
        input_preview = json.dumps(tool_input)[:300]
        log.info("   INPUT  %s%s", input_preview, "…" if len(json.dumps(tool_input)) > 300 else "")

        result_json = execute_tool(tool_name, tool_input)

        # Parse result just for logging — keep raw JSON to return
        try:
            result_data = json.loads(result_json)
            status = "OK" if result_data.get("success", result_data.get("found", True)) else "FAIL"
            # Pull a meaningful excerpt for the log line
            if "error" in result_data:
                detail = result_data["error"][:120]
            elif "action" in result_data:
                detail = result_data["action"]
            elif "template" in result_data:
                detail = f"template_matched={result_data.get('template_matched')}"
            else:
                detail = json.dumps(result_data)[:120]
            log.info("   RESULT  status=%s  %s", status, detail)
        except Exception:
            log.info("   RESULT  (raw) %s", result_json[:200])

        return result_json

    @staticmethod
    def _extract_text(content_blocks) -> str:
        """Return the concatenated text from all text blocks in a response."""
        parts = [
            b.text for b in content_blocks
            if getattr(b, "type", None) == "text"
        ]
        return "\n\n".join(parts).strip()

    @staticmethod
    def _log_section(title: str):
        log.info("=" * 64)
        log.info(title)
        log.info("=" * 64)
