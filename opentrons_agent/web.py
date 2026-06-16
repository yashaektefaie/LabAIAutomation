"""
Gradio web interface for the Opentrons protocol generation agent.

Provides:
  - Chat interface for describing experiments and refining protocols
  - File upload for CSVs, plate maps, and existing protocols
  - Protocol download
  - Session reset

Usage:
    python -m opentrons_agent.web
    # or: opentrons-agent-web
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

import gradio as gr

from .agent import OpentronAgent
from .data_ingestion import read_file
from .profile import EMPTY_PROFILE, load_profile, save_profile
from .settings import get_settings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CSS = """
.gradio-container { max-width: 1200px !important; margin-left: auto !important; margin-right: auto !important; }
.chatbot { min-height: 500px; }
"""

_THEME = gr.themes.Soft(primary_hue="blue", secondary_hue="slate")


def extract_last_code_block(text: str) -> str | None:
    """Pull the last ```python ... ``` block from markdown text."""
    matches = re.findall(r"```python\n(.*?)```", text, re.DOTALL)
    return matches[-1].strip() if matches else None


# ---------------------------------------------------------------------------
# State management — one agent per browser session
# ---------------------------------------------------------------------------

def get_or_create_agent(state: dict) -> OpentronAgent:
    """Get the agent from session state, or create one."""
    if "agent" not in state:
        settings = get_settings()
        state["agent"] = OpentronAgent(settings)
        state["last_protocol"] = None
    return state["agent"]


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------

def on_message(user_message: str, chat_history: list, files: list | None, state: dict):
    """Handle a user message in the chat, streaming thinking and response text."""
    agent = get_or_create_agent(state)

    # Process any newly uploaded files
    file_notes = []
    if files:
        for file_path in files:
            path = Path(file_path)
            if path.exists():
                attachment = read_file(path)
                msg = agent.add_attachment(attachment)
                file_notes.append(msg)

    # Build the display message (show file attachments in the chat)
    display_message = user_message
    if file_notes:
        file_summary = "\n".join(f"Attached: {note}" for note in file_notes)
        display_message = f"{file_summary}\n\n{user_message}"

    # Add user message to chat history
    chat_history = chat_history + [{"role": "user", "content": display_message}]

    # Yield the user message immediately so it shows up
    yield chat_history, state, gr.update(value=None), gr.update(interactive=False)

    # Stream agent response with live thinking trace
    thinking_text = ""
    response_text = ""
    has_thinking = False

    try:
        for event_type, chunk in agent.chat_stream(user_message):
            if event_type == "thinking":
                has_thinking = True
                thinking_text += chunk
                # Show thinking in a collapsible details block + partial response
                assembled = _assemble_streaming_response(thinking_text, response_text, thinking_done=False)
                chat_history_with_assistant = chat_history + [{"role": "assistant", "content": assembled}]
                yield chat_history_with_assistant, state, gr.update(value=None), gr.update(interactive=False)

            elif event_type == "text":
                response_text += chunk
                assembled = _assemble_streaming_response(thinking_text, response_text, thinking_done=True)
                chat_history_with_assistant = chat_history + [{"role": "assistant", "content": assembled}]
                yield chat_history_with_assistant, state, gr.update(value=None), gr.update(interactive=False)

            elif event_type == "tool_start":
                response_text += f"\n\n*Running tool: {chunk}...*\n"
            elif event_type == "tool_result":
                snippet = chunk[:300] + ("..." if len(chunk) > 300 else "")
                response_text += f"\n```\n{snippet}\n```\n"

    except Exception as e:
        response_text += f"\n\n**Error:** {e}"

    # Final assembled response
    final_response = _assemble_streaming_response(thinking_text, response_text, thinking_done=True)

    # Track the last protocol
    code = extract_last_code_block(response_text)
    if code:
        state["last_protocol"] = code

    chat_history = chat_history + [{"role": "assistant", "content": final_response}]
    yield chat_history, state, gr.update(value=None), gr.update(interactive=True)


def _assemble_streaming_response(thinking: str, text: str, thinking_done: bool) -> str:
    """Combine thinking trace and response text into a single markdown string."""
    parts = []
    if thinking:
        # Keep <details> open while streaming so re-renders don't collapse it
        open_attr = "" if thinking_done else " open"
        status = "" if thinking_done else " *(reasoning...)*"
        parts.append(f"<details{open_attr}><summary>Reasoning trace{status}</summary>\n\n{thinking}\n\n</details>")
    if text:
        parts.append(text)
    if not parts:
        return "*Thinking...*"
    return "\n\n".join(parts)


def on_reset(state: dict):
    """Reset the conversation."""
    if "agent" in state:
        state["agent"].reset()
    state["last_protocol"] = None
    return [], state


def on_download(state: dict) -> str | None:
    """Download the last generated protocol as a .py file."""
    code = state.get("last_protocol")
    if not code:
        gr.Warning("No protocol has been generated yet.")
        return None

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", prefix="opentrons_protocol_", delete=False
    )
    tmp.write(code)
    tmp.close()
    return tmp.name


# ---------------------------------------------------------------------------
# Machine profile handlers
# ---------------------------------------------------------------------------

def _format_profile_display(profile: dict) -> str:
    """Format the profile as a readable markdown summary."""
    if not profile.get("robot_type") and not any(profile.get("pipettes", {}).values()):
        return "*No profile saved yet.*"
    lines = []
    if profile.get("robot_type"):
        lines.append(f"**Robot:** {profile['robot_type']}")
    pip = profile.get("pipettes", {})
    if pip.get("left"):
        lines.append(f"**Left:** {pip['left']}")
    if pip.get("right"):
        lines.append(f"**Right:** {pip['right']}")
    if profile.get("modules"):
        lines.append(f"**Modules:** {', '.join(profile['modules'])}")
    if profile.get("default_labware"):
        lines.append(f"**Labware:** {', '.join(profile['default_labware'])}")
    if profile.get("default_tip_racks"):
        lines.append(f"**Tips:** {', '.join(profile['default_tip_racks'])}")
    if profile.get("notes"):
        lines.append(f"**Notes:** {profile['notes']}")
    return "\n".join(lines)


def on_load_profile():
    """Load the current profile into the form fields."""
    p = load_profile()
    pip = p.get("pipettes", {})
    return (
        p.get("robot_type", ""),
        pip.get("left", ""),
        pip.get("right", ""),
        ", ".join(p.get("modules", [])),
        ", ".join(p.get("default_labware", [])),
        ", ".join(p.get("default_tip_racks", [])),
        p.get("notes", ""),
        _format_profile_display(p),
    )


def on_save_profile(robot_type, left_pip, right_pip, modules, labware, tip_racks, notes, state):
    """Save profile from form fields."""
    profile = {
        "robot_type": robot_type.strip(),
        "pipettes": {
            "left": left_pip.strip(),
            "right": right_pip.strip(),
        },
        "modules": [m.strip() for m in modules.split(",") if m.strip()] if modules.strip() else [],
        "default_labware": [l.strip() for l in labware.split(",") if l.strip()] if labware.strip() else [],
        "default_tip_racks": [t.strip() for t in tip_racks.split(",") if t.strip()] if tip_racks.strip() else [],
        "notes": notes.strip(),
    }
    save_profile(profile)
    # Reload in the agent if it exists
    if "agent" in state:
        state["agent"].reload_profile()
    gr.Info("Machine profile saved.")
    return _format_profile_display(profile), state


def on_clear_profile(state):
    """Clear the saved profile."""
    save_profile(dict(EMPTY_PROFILE))
    if "agent" in state:
        state["agent"].reload_profile()
    gr.Info("Machine profile cleared.")
    return (
        "", "", "", "", "", "", "",
        _format_profile_display(EMPTY_PROFILE),
        state,
    )


# ---------------------------------------------------------------------------
# UI Layout
# ---------------------------------------------------------------------------

def create_app() -> gr.Blocks:
    with gr.Blocks(title="Opentrons Protocol Agent") as app:
        # Session state
        session_state = gr.State({})

        gr.Markdown(
            "# Opentrons Protocol Agent\n"
            "Describe your experiment and I'll generate a validated Opentrons protocol. "
            "Upload CSV plate data (concentrations, sample maps) to create data-driven protocols."
        )

        with gr.Row():
            # ---- Main chat column ----
            with gr.Column(scale=4):
                chatbot = gr.Chatbot(
                    elem_classes="chatbot",
                    render_markdown=True,
                    placeholder=(
                        "**Welcome!** Describe your experiment to get started.\n\n"
                        "Examples:\n"
                        "- \"Normalize a plate of DNA to 5 ng/uL using a Flex\"\n"
                        "- \"Set up a serial dilution across 12 columns on an OT-2\"\n"
                        "- \"PCR setup: distribute master mix then add 8 samples\""
                    ),
                )

                with gr.Row():
                    msg_input = gr.Textbox(
                        placeholder="Describe your experiment or ask a question...",
                        show_label=False,
                        scale=5,
                        lines=2,
                        max_lines=6,
                    )
                    send_btn = gr.Button("Send", variant="primary", scale=1, min_width=80)

            # ---- Sidebar ----
            with gr.Column(scale=1, min_width=250):
                gr.Markdown("### Data Files")
                file_upload = gr.File(
                    label="Upload plate data",
                    file_types=[".csv", ".tsv", ".txt", ".py"],
                    file_count="multiple",
                    type="filepath",
                )
                gr.Markdown(
                    "<small>Upload CSVs with well positions, concentrations, "
                    "sample IDs, or existing Python protocols.</small>"
                )

                gr.Markdown("### Actions")
                with gr.Row():
                    download_btn = gr.DownloadButton("Download .py", variant="secondary")
                reset_btn = gr.Button("Reset Session", variant="stop")

                # ---- Machine Profile ----
                with gr.Accordion("Machine Profile", open=False):
                    profile_display = gr.Markdown(_format_profile_display(load_profile()))
                    with gr.Column():
                        prof_robot = gr.Dropdown(
                            choices=["", "OT-2", "Flex"], label="Robot type", value=""
                        )
                        prof_left = gr.Textbox(label="Left mount pipette", placeholder="e.g. p300_single_gen2")
                        prof_right = gr.Textbox(label="Right mount pipette", placeholder="e.g. p20_multi_gen2")
                        prof_modules = gr.Textbox(label="Modules (comma-separated)", placeholder="e.g. temperature module gen2, thermocyclerModuleV2")
                        prof_labware = gr.Textbox(label="Preferred labware (comma-separated)", placeholder="e.g. nest_96_wellplate_100ul_pcr_full_skirt")
                        prof_tips = gr.Textbox(label="Preferred tip racks (comma-separated)", placeholder="e.g. opentrons_96_tiprack_300ul")
                        prof_notes = gr.Textbox(label="Notes", placeholder="e.g. Always use filter tips", lines=2)
                        with gr.Row():
                            prof_save_btn = gr.Button("Save Profile", variant="primary", size="sm")
                            prof_clear_btn = gr.Button("Clear", variant="stop", size="sm")

                gr.Markdown(
                    "### Tips\n"
                    "- Set your **machine profile** so the agent knows your setup\n"
                    "- Upload a **CSV** with concentrations for normalization protocols\n"
                    "- Click **Download .py** to save the protocol"
                )

        # ---- Event wiring ----

        # Send message (button or Enter)
        send_event_args = dict(
            fn=on_message,
            inputs=[msg_input, chatbot, file_upload, session_state],
            outputs=[chatbot, session_state, file_upload, send_btn],
        )
        msg_input.submit(**send_event_args).then(
            lambda: "", outputs=[msg_input]
        )
        send_btn.click(**send_event_args).then(
            lambda: "", outputs=[msg_input]
        )

        # Download
        download_btn.click(
            fn=on_download,
            inputs=[session_state],
            outputs=[download_btn],
        )

        # Reset
        reset_btn.click(
            fn=on_reset,
            inputs=[session_state],
            outputs=[chatbot, session_state],
        )

        # Profile — load current values when accordion opens
        profile_fields = [prof_robot, prof_left, prof_right, prof_modules, prof_labware, prof_tips, prof_notes, profile_display]

        # Save profile
        prof_save_btn.click(
            fn=on_save_profile,
            inputs=[prof_robot, prof_left, prof_right, prof_modules, prof_labware, prof_tips, prof_notes, session_state],
            outputs=[profile_display, session_state],
        )

        # Clear profile
        prof_clear_btn.click(
            fn=on_clear_profile,
            inputs=[session_state],
            outputs=[prof_robot, prof_left, prof_right, prof_modules, prof_labware, prof_tips, prof_notes, profile_display, session_state],
        )

        # Load saved profile values into form on app load
        app.load(fn=on_load_profile, outputs=profile_fields)

    return app


def main():
    app = create_app()
    app.launch(share=False, theme=_THEME, css=_CSS)


if __name__ == "__main__":
    main()
