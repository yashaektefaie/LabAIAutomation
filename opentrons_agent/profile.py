"""
Machine profile: persists robot setup across sessions.

Stores robot type, pipettes, modules, preferred labware, and free-form notes
in a JSON file so the agent doesn't have to ask about hardware every time.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_PROFILE_PATH = Path.home() / ".opentrons_agent" / "machine_profile.json"

EMPTY_PROFILE: dict[str, Any] = {
    "robot_type": "",           # "OT-2" or "Flex"
    "pipettes": {
        "left": "",             # e.g. "p300_single_gen2"
        "right": "",            # e.g. "p20_multi_gen2"
    },
    "modules": [],              # e.g. ["temperature module gen2", "thermocyclerModuleV2"]
    "default_labware": [],      # e.g. ["nest_96_wellplate_100ul_pcr_full_skirt"]
    "default_tip_racks": [],    # e.g. ["opentrons_96_tiprack_300ul"]
    "notes": "",                # free-form text: "We always use filter tips", etc.
}


def load_profile(path: Path = DEFAULT_PROFILE_PATH) -> dict[str, Any]:
    """Load the machine profile from disk, or return an empty profile."""
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return dict(EMPTY_PROFILE)


def save_profile(profile: dict[str, Any], path: Path = DEFAULT_PROFILE_PATH) -> None:
    """Save the machine profile to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")


def profile_to_prompt(profile: dict[str, Any]) -> str:
    """Convert a machine profile to a prompt section for the agent."""
    # Skip if profile is effectively empty
    if not profile.get("robot_type") and not any(profile.get("pipettes", {}).values()):
        return ""

    lines = ["<machine_profile>", "The user has a saved machine profile. Use these defaults unless they say otherwise:", ""]

    if profile.get("robot_type"):
        lines.append(f"Robot type: {profile['robot_type']}")

    pipettes = profile.get("pipettes", {})
    if pipettes.get("left"):
        lines.append(f"Left mount: {pipettes['left']}")
    if pipettes.get("right"):
        lines.append(f"Right mount: {pipettes['right']}")

    if profile.get("modules"):
        lines.append(f"Modules: {', '.join(profile['modules'])}")

    if profile.get("default_labware"):
        lines.append(f"Preferred labware: {', '.join(profile['default_labware'])}")

    if profile.get("default_tip_racks"):
        lines.append(f"Preferred tip racks: {', '.join(profile['default_tip_racks'])}")

    if profile.get("notes"):
        lines.append(f"Notes: {profile['notes']}")

    lines.append("</machine_profile>")
    return "\n".join(lines)
