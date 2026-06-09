"""
main.py — CLI entry point for the IT Onboarding/Offboarding Workflow Agent.

Run:
    python main.py

Set ANTHROPIC_API_KEY in a .env file (copy from .env.example).
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv()

from agent import OnboardingAgent


BANNER = """\
╔══════════════════════════════════════════════════════════════╗
║     IT Onboarding / Offboarding Workflow Orchestrator        ║
║     Powered by Claude AI  ·  MCP Tool-Calling Demo           ║
╚══════════════════════════════════════════════════════════════╝

The agent reads your request in plain English and autonomously
determines which IT actions to take (AD, Exchange, M365, etc.).

Example requests:
  • Onboard Sarah Chen as a Software Engineer in Engineering,
    starting 2026-06-16, manager is rjohnson
  • Immediately offboard jsmith — security incident
  • Check the status of Maria Williams
  • Onboard a new Finance Manager named David Park

Type  quit  or  exit  to stop.
"""

SEPARATOR = "─" * 64


def main():
    print(BANNER)

    model = os.environ.get("CLAUDE_MODEL", "claude-opus-4-8")
    try:
        agent = OnboardingAgent(model=model, max_iterations=20)
    except EnvironmentError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    print(f"[Model: {model}]\n")

    while True:
        try:
            request = input("Request > ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            break

        if not request:
            continue

        if request.lower() in ("quit", "exit", "q"):
            print("Goodbye.")
            break

        print(f"\n{SEPARATOR}")
        print("[Agent working — see trace below]\n")

        final = agent.run(request)

        print(f"\n{SEPARATOR}")
        print("[AGENT RESPONSE]\n")
        print(final)
        print(f"\n{SEPARATOR}\n")

        try:
            followup = input("Continue this conversation? [y/N] > ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            break

        if followup != "y":
            agent.reset()
            print("Conversation reset.\n")


if __name__ == "__main__":
    main()
