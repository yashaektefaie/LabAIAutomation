"""
Machine-readable CLI for agent-to-agent interaction.

Designed for non-interactive use by outer AI agents (Claude Code, Codex, etc.).
All output is JSON to stdout. No colors, no prompts, no streaming display.

Usage:
    opentrons-agent-api --new-session --message "Design a serial dilution on Flex"
    opentrons-agent-api --session <id> --message "Use p1000 single channel"
    opentrons-agent-api --session <id> --attach plate_map.csv --message "Normalize to 5ng/uL"
    opentrons-agent-api --session <id> --get-protocol
    opentrons-agent-api --session <id> --get-history
    opentrons-agent-api --list-sessions
    opentrons-agent-api --delete-session <id>
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .agent import OpentronAgent
from .data_ingestion import FileAttachment, read_file
from .settings import get_settings

SESSIONS_DIR = Path.home() / ".opentrons_agent" / "sessions"


def _output(data: dict[str, Any]) -> None:
    json.dump(data, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    sys.stdout.flush()


def _error(message: str, session_id: str | None = None) -> None:
    _output({
        "ok": False,
        "session_id": session_id,
        "type": "error",
        "response": None,
        "has_protocol": False,
        "protocol": None,
        "turn": None,
        "error": message,
    })
    sys.exit(1)


def _response(
    session_id: str,
    response_type: str,
    response: str | None = None,
    protocol: str | None = None,
    turn: int | None = None,
    history: list | None = None,
) -> None:
    data: dict[str, Any] = {
        "ok": True,
        "session_id": session_id,
        "type": response_type,
        "response": response,
        "has_protocol": protocol is not None,
        "protocol": protocol,
        "turn": turn,
        "error": None,
    }
    if history is not None:
        data["history"] = history
    _output(data)


def _extract_last_code_block(text: str) -> str | None:
    matches = re.findall(r"```python\n(.*?)```", text, re.DOTALL)
    return matches[-1].strip() if matches else None


def _save_session(session_id: str, agent: OpentronAgent, turn: int) -> None:
    session_dir = SESSIONS_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "session_id": session_id,
        "turn": turn,
        "history": agent._history,
        "attachments": [
            {"name": a.name, "content": a.content, "file_type": a.file_type}
            for a in agent._attachments
        ],
    }
    (session_dir / "state.json").write_text(
        json.dumps(state, ensure_ascii=False), encoding="utf-8"
    )


def _load_session(session_id: str) -> tuple[OpentronAgent, int]:
    state_file = SESSIONS_DIR / session_id / "state.json"
    if not state_file.exists():
        _error(f"Session not found: {session_id}", session_id)

    state = json.loads(state_file.read_text(encoding="utf-8"))
    agent = OpentronAgent(get_settings())
    agent._history = state["history"]
    agent._attachments = [
        FileAttachment(name=a["name"], content=a["content"], file_type=a["file_type"])
        for a in state.get("attachments", [])
    ]
    return agent, state["turn"]


def _get_last_assistant_text(history: list) -> str:
    for entry in reversed(history):
        if entry.get("role") == "assistant":
            content = entry.get("content", "")
            if isinstance(content, str):
                return content
    return ""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Machine-readable CLI for Opentrons protocol agent (JSON I/O)",
    )

    session_group = parser.add_mutually_exclusive_group()
    session_group.add_argument(
        "--new-session", action="store_true",
        help="Create a new conversation session",
    )
    session_group.add_argument(
        "--session", type=str, metavar="ID",
        help="Continue an existing session by ID",
    )
    session_group.add_argument(
        "--list-sessions", action="store_true",
        help="List all saved sessions",
    )
    session_group.add_argument(
        "--delete-session", type=str, metavar="ID",
        help="Delete a saved session",
    )

    msg_group = parser.add_mutually_exclusive_group()
    msg_group.add_argument(
        "--message", "-m", type=str,
        help="Message to send to the agent",
    )
    msg_group.add_argument(
        "--message-stdin", action="store_true",
        help="Read message from stdin",
    )

    parser.add_argument(
        "--attach", "-a", action="append", default=[],
        help="Attach a file (can be repeated)",
    )
    parser.add_argument(
        "--get-protocol", action="store_true",
        help="Extract the last protocol from the conversation",
    )
    parser.add_argument(
        "--get-history", action="store_true",
        help="Dump conversation history",
    )

    args = parser.parse_args()

    if args.list_sessions:
        _handle_list_sessions()
        return

    if args.delete_session:
        _handle_delete_session(args.delete_session)
        return

    if args.new_session:
        _handle_new_session(args)
        return

    if args.session:
        _handle_existing_session(args)
        return

    _error("Must specify --new-session, --session <id>, --list-sessions, or --delete-session <id>")


def _handle_list_sessions() -> None:
    if not SESSIONS_DIR.exists():
        _output({"ok": True, "type": "session_list", "sessions": []})
        return

    sessions = []
    for d in sorted(SESSIONS_DIR.iterdir()):
        state_file = d / "state.json"
        if state_file.exists():
            state = json.loads(state_file.read_text(encoding="utf-8"))
            sessions.append({
                "session_id": state["session_id"],
                "turn": state["turn"],
            })
    _output({"ok": True, "type": "session_list", "sessions": sessions})


def _handle_delete_session(session_id: str) -> None:
    session_dir = SESSIONS_DIR / session_id
    if not session_dir.exists():
        _error(f"Session not found: {session_id}", session_id)
    shutil.rmtree(session_dir)
    _output({
        "ok": True,
        "session_id": session_id,
        "type": "session_deleted",
        "response": None,
        "has_protocol": False,
        "protocol": None,
        "turn": None,
        "error": None,
    })


def _handle_new_session(args: argparse.Namespace) -> None:
    session_id = uuid.uuid4().hex[:12]

    try:
        agent = OpentronAgent(get_settings())
    except Exception as e:
        _error(f"Failed to initialize agent: {e}", session_id)

    turn = 0

    for file_path in args.attach:
        path = Path(file_path)
        if not path.exists():
            _error(f"File not found: {path}", session_id)
        agent.add_attachment(read_file(path))

    message = _get_message(args)

    if message:
        try:
            response_text = agent.chat(message)
        except Exception as e:
            _error(f"Agent error: {e}", session_id)
        turn = 1
        protocol = _extract_last_code_block(response_text)
        _save_session(session_id, agent, turn)
        _response(session_id, "chat_response", response_text, protocol, turn)
    else:
        _save_session(session_id, agent, turn)
        _response(session_id, "session_created", turn=turn)


def _handle_existing_session(args: argparse.Namespace) -> None:
    session_id = args.session
    agent, turn = _load_session(session_id)

    for file_path in args.attach:
        path = Path(file_path)
        if not path.exists():
            _error(f"File not found: {path}", session_id)
        agent.add_attachment(read_file(path))

    if args.get_protocol:
        last_text = _get_last_assistant_text(agent._history)
        protocol = _extract_last_code_block(last_text)
        _response(session_id, "protocol", protocol=protocol, turn=turn)
        return

    if args.get_history:
        _response(session_id, "history", turn=turn, history=agent._history)
        return

    message = _get_message(args)
    if not message and not args.attach:
        _error(
            "No action specified. Use --message, --get-protocol, or --get-history",
            session_id,
        )

    if message:
        try:
            response_text = agent.chat(message)
        except Exception as e:
            _error(f"Agent error: {e}", session_id)
        turn += 1
        protocol = _extract_last_code_block(response_text)
        _save_session(session_id, agent, turn)
        _response(session_id, "chat_response", response_text, protocol, turn)
    else:
        _save_session(session_id, agent, turn)
        _response(session_id, "attachments_added", turn=turn)


def _get_message(args: argparse.Namespace) -> str | None:
    if args.message:
        return args.message
    if args.message_stdin:
        return sys.stdin.read().strip() or None
    return None


if __name__ == "__main__":
    main()
