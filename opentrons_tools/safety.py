from __future__ import annotations

CONFIRMATION_PHRASE = "ACTIONS_CAN_MOVE_HARDWARE"


class SafetyError(RuntimeError):
    """Raised when a command that can affect hardware is not confirmed."""


def require_action_confirmation(allow_action: bool, confirmation: str | None) -> None:
    if allow_action and confirmation == CONFIRMATION_PHRASE:
        return
    raise SafetyError(
        "This command can mutate robot state or move hardware. Re-run with "
        f"--allow-action --confirm {CONFIRMATION_PHRASE}"
    )
