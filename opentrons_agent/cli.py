"""
Interactive CLI for the Opentrons protocol generation agent.

Usage:
    opentrons-agent                  # start interactive session
    opentrons-agent --attach data.csv  # start with a file pre-loaded

Commands during a session:
    /attach <path>    Load a CSV, Python, or text file as context
    /profile          Show the saved machine profile
    /profile set      Interactively configure the machine profile
    /profile clear    Remove the saved machine profile
    /reset            Clear conversation history and attachments
    /save <path>      Save the last protocol to a file
    /quit or /exit    Exit
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from .agent import OpentronAgent
from .data_ingestion import read_file
from .profile import EMPTY_PROFILE, load_profile, save_profile
from .settings import get_settings

console = Console()


def extract_last_code_block(text: str) -> str | None:
    """Extract the last Python code block from markdown-formatted text."""
    pattern = r"```python\n(.*?)```"
    matches = re.findall(pattern, text, re.DOTALL)
    return matches[-1].strip() if matches else None


def _prompt(label: str, default: str = "") -> str:
    """Prompt for input with an optional default."""
    suffix = f" [{default}]" if default else ""
    try:
        value = console.input(f"  {label}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        return default
    return value or default


def _prompt_list(label: str, current: list[str]) -> list[str]:
    """Prompt for a comma-separated list with an optional default."""
    default = ", ".join(current)
    raw = _prompt(f"{label} (comma-separated)", default)
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def handle_profile(sub: str, agent: OpentronAgent) -> str:
    """Handle /profile subcommands."""
    if sub in ("", "show"):
        profile = load_profile()
        if not profile.get("robot_type") and not any(profile.get("pipettes", {}).values()):
            return "No machine profile saved. Use /profile set to create one."
        table = Table(title="Machine Profile", show_header=False, border_style="blue")
        table.add_column("Field", style="bold")
        table.add_column("Value")
        table.add_row("Robot", profile.get("robot_type", "—"))
        pip = profile.get("pipettes", {})
        table.add_row("Left pipette", pip.get("left", "—") or "—")
        table.add_row("Right pipette", pip.get("right", "—") or "—")
        table.add_row("Modules", ", ".join(profile.get("modules", [])) or "—")
        table.add_row("Labware", ", ".join(profile.get("default_labware", [])) or "—")
        table.add_row("Tip racks", ", ".join(profile.get("default_tip_racks", [])) or "—")
        table.add_row("Notes", profile.get("notes", "") or "—")
        console.print(table)
        return ""

    if sub == "set":
        profile = load_profile()
        console.print("[bold]Configure machine profile[/bold] (press Enter to keep current value)\n")
        profile["robot_type"] = _prompt("Robot type (OT-2 / Flex)", profile.get("robot_type", ""))
        pip = profile.get("pipettes", {})
        pip["left"] = _prompt("Left mount pipette", pip.get("left", ""))
        pip["right"] = _prompt("Right mount pipette", pip.get("right", ""))
        profile["pipettes"] = pip
        profile["modules"] = _prompt_list("Modules", profile.get("modules", []))
        profile["default_labware"] = _prompt_list("Preferred labware", profile.get("default_labware", []))
        profile["default_tip_racks"] = _prompt_list("Preferred tip racks", profile.get("default_tip_racks", []))
        profile["notes"] = _prompt("Notes (free-form)", profile.get("notes", ""))
        save_profile(profile)
        agent.reload_profile()
        return "Profile saved. The agent will use these defaults for all future sessions."

    if sub == "clear":
        save_profile(dict(EMPTY_PROFILE))
        agent.reload_profile()
        return "Machine profile cleared."

    return f"Unknown subcommand: /profile {sub}. Use /profile, /profile set, or /profile clear."


def handle_command(cmd: str, args: str, agent: OpentronAgent, last_response: str) -> str | None:
    """Handle a slash command. Returns a message to display, or None."""
    if cmd in ("/quit", "/exit"):
        console.print("[dim]Goodbye![/dim]")
        sys.exit(0)

    if cmd == "/reset":
        agent.reset()
        return "Session reset. History and attachments cleared."

    if cmd == "/profile":
        return handle_profile(args.strip(), agent)

    if cmd == "/attach":
        path = Path(args.strip())
        if not path.exists():
            return f"File not found: {path}"
        try:
            attachment = read_file(path)
            msg = agent.add_attachment(attachment)
            return f"Attached: {msg}"
        except Exception as e:
            return f"Error reading file: {e}"

    if cmd == "/save":
        dest = Path(args.strip()) if args.strip() else Path("protocol.py")
        code = extract_last_code_block(last_response)
        if not code:
            return "No Python code block found in the last response."
        dest.write_text(code, encoding="utf-8")
        return f"Protocol saved to {dest}"

    return f"Unknown command: {cmd}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Opentrons protocol generation agent")
    parser.add_argument(
        "--attach", "-a",
        action="append",
        default=[],
        help="Attach a data file (CSV, Python, text) at startup",
    )
    args = parser.parse_args()

    console.print(
        Panel(
            "[bold]Opentrons Protocol Agent[/bold]\n"
            "Describe your experiment and I'll generate an Opentrons protocol.\n"
            "You can attach data files with [bold]/attach path/to/file.csv[/bold]\n"
            "Type [bold]/quit[/bold] to exit.",
            border_style="blue",
        )
    )

    try:
        settings = get_settings()
    except KeyError:
        console.print(
            "[red]Error:[/red] ANTHROPIC_API_KEY not set. "
            "Copy .env.example to .env and fill in your key."
        )
        sys.exit(1)

    agent = OpentronAgent(settings)

    # Pre-load any attachments from CLI args
    for file_path in args.attach:
        path = Path(file_path)
        if not path.exists():
            console.print(f"[yellow]Warning:[/yellow] File not found: {path}")
            continue
        attachment = read_file(path)
        msg = agent.add_attachment(attachment)
        console.print(f"[green]{msg}[/green]")

    last_response = ""

    while True:
        try:
            user_input = console.input("\n[bold blue]You:[/bold blue] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye![/dim]")
            break

        if not user_input:
            continue

        # Handle slash commands
        if user_input.startswith("/"):
            parts = user_input.split(maxsplit=1)
            cmd = parts[0]
            cmd_args = parts[1] if len(parts) > 1 else ""

            result = handle_command(cmd, cmd_args, agent, last_response)
                if result:
                    console.print(f"[dim]{result}[/dim]")
                continue

        # Stream the response with live thinking trace
        console.print()
        response_text = ""
        in_thinking = False
        in_text = False
        try:
            for event_type, chunk in agent.chat_stream(user_input):
                if event_type == "thinking":
                    if not in_thinking:
                        in_thinking = True
                        console.print("[dim italic]Reasoning...[/dim italic]")
                    console.print(f"[dim]{chunk}[/dim]", end="", highlight=False)
                elif event_type == "text":
                    if in_thinking and not in_text:
                        in_thinking = False
                        console.print("\n")  # blank line after thinking
                    in_text = True
                    response_text += chunk
                    console.print(chunk, end="", highlight=False)
                elif event_type == "tool_start":
                    console.print(f"\n[yellow]Running tool: {chunk}...[/yellow]")
                elif event_type == "tool_result":
                    console.print(f"[dim]Tool result: {chunk[:200]}{'...' if len(chunk) > 200 else ''}[/dim]")
        except Exception as e:
            console.print(f"\n[red]Error:[/red] {e}")
            continue

        console.print()  # final newline
        last_response = response_text


if __name__ == "__main__":
    main()
