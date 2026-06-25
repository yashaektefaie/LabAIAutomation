from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path
from typing import Any

from .client import HostConfig, PrepClient, PrepResponse
from .output import emit_json
from .safety import CONFIRMATION_PHRASE, SafetyError, require_action_confirmation


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        result = args.handler(args)
    except SafetyError as error:
        emit_json({"ok": False, "error": str(error)})
        return 3
    except FileNotFoundError as error:
        emit_json({"ok": False, "error": str(error)})
        return 3
    except json.JSONDecodeError as error:
        emit_json({"ok": False, "error": f"Invalid JSON: {error}"})
        return 3
    except KeyboardInterrupt:
        emit_json({"ok": False, "error": "Interrupted"})
        return 130

    if isinstance(result, PrepResponse):
        emit_json(result.to_jsonable())
        return 0 if result.ok else 2
    emit_json(result)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hamilton-tools",
        description="Agent-friendly Hamilton Microlab Prep tools.",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("HAMILTON_HOST"),
        help="Prep hostname/IP. Can also be set with HAMILTON_HOST.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=_env_int("HAMILTON_PORT"),
        help="Prep HTTP API port. Can also be set with HAMILTON_PORT.",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("HAMILTON_TOKEN"),
        help="Pre-existing JWT token. Can also be set with HAMILTON_TOKEN.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("HAMILTON_TIMEOUT", "10")),
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--https",
        action="store_true",
        default=os.environ.get("HAMILTON_HTTPS", "").lower() in ("1", "true", "yes"),
        help="Use HTTPS instead of HTTP.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # ── Authentication ──────────────────────────────────────────────

    login = subparsers.add_parser("login", help="Authenticate and print JWT token.")
    login.add_argument("--username", default=os.environ.get("HAMILTON_USER"))
    login.add_argument(
        "--password",
        default=os.environ.get("HAMILTON_PASSWORD"),
        help="If omitted and not in HAMILTON_PASSWORD, will prompt interactively.",
    )
    login.set_defaults(handler=handle_login)

    subparsers.add_parser("check-auth", help="Check if the current token is valid.").set_defaults(
        handler=handle_check_auth
    )

    renew = subparsers.add_parser("renew-token", help="Renew the JWT token.")
    renew.set_defaults(handler=handle_renew_token)

    logout = subparsers.add_parser("logout", help="Log out and invalidate the token.")
    logout.set_defaults(handler=handle_logout)

    # ── System health ───────────────────────────────────────────────

    subparsers.add_parser("system-ready", help="Check if the system is ready.").set_defaults(
        handler=handle_system_ready
    )

    subparsers.add_parser("software-versions", help="Get software version info.").set_defaults(
        handler=handle_software_versions
    )

    subparsers.add_parser("environment", help="Get environment info.").set_defaults(
        handler=handle_environment
    )

    subparsers.add_parser(
        "snapshot", help="Read a broad non-mutating status snapshot."
    ).set_defaults(handler=handle_snapshot)

    # ── Errors ──────────────────────────────────────────────────────

    subparsers.add_parser("errors", help="Get current errors.").set_defaults(
        handler=handle_errors
    )

    subparsers.add_parser("runtime-errors", help="Get runtime errors.").set_defaults(
        handler=handle_runtime_errors
    )

    clear_errs = subparsers.add_parser("clear-errors", help="Clear all errors.")
    add_action_flags(clear_errs)
    clear_errs.set_defaults(handler=handle_clear_errors)

    # ── Instruments ─────────────────────────────────────────────────

    subparsers.add_parser("instruments", help="Get instrument info.").set_defaults(
        handler=handle_instruments
    )

    subparsers.add_parser(
        "connection-status", help="Get instrument connection status."
    ).set_defaults(handler=handle_connection_status)

    subparsers.add_parser("run-state", help="Get global run state.").set_defaults(
        handler=handle_run_state
    )

    subparsers.add_parser("serial-number", help="Get instrument serial number.").set_defaults(
        handler=handle_serial_number
    )

    init_inst = subparsers.add_parser("initialize", help="Initialize the instrument.")
    add_action_flags(init_inst)
    init_inst.set_defaults(handler=handle_initialize)

    mock_inst = subparsers.add_parser("use-mock", help="Switch to mock instrument.")
    add_action_flags(mock_inst)
    mock_inst.set_defaults(handler=handle_use_mock)

    # ── Protocols ───────────────────────────────────────────────────

    subparsers.add_parser("list-protocols", help="List all protocols.").set_defaults(
        handler=handle_list_protocols
    )

    get_proto = subparsers.add_parser("get-protocol", help="Get a protocol by ID.")
    get_proto.add_argument("protocol_id", type=int)
    get_proto.set_defaults(handler=handle_get_protocol)

    subparsers.add_parser("protocol-names", help="Get all protocol names.").set_defaults(
        handler=handle_protocol_names
    )

    verify_proto = subparsers.add_parser("verify-protocol", help="Verify a protocol.")
    verify_proto.add_argument("protocol_id", type=int)
    verify_proto.set_defaults(handler=handle_verify_protocol)

    validate_proto = subparsers.add_parser("validate-protocol", help="Validate a protocol.")
    validate_proto.add_argument("protocol_id", type=int)
    validate_proto.set_defaults(handler=handle_validate_protocol)

    preview_proto = subparsers.add_parser("preview-protocol", help="Preview a protocol run.")
    preview_proto.add_argument("protocol_id", type=int)
    preview_proto.set_defaults(handler=handle_preview_protocol)

    import_proto = subparsers.add_parser("import-protocols", help="Import protocols from file.")
    import_proto.add_argument("file", type=Path)
    add_action_flags(import_proto)
    import_proto.set_defaults(handler=handle_import_protocols)

    # ── Protocol steps ──────────────────────────────────────────────

    list_steps = subparsers.add_parser("list-steps", help="List steps in a protocol.")
    list_steps.add_argument("protocol_id", type=int)
    list_steps.set_defaults(handler=handle_list_steps)

    get_step = subparsers.add_parser("get-step", help="Get a specific step.")
    get_step.add_argument("protocol_id", type=int)
    get_step.add_argument("step_id", type=int)
    get_step.set_defaults(handler=handle_get_step)

    # ── Protocol run ────────────────────────────────────────────────

    create_run = subparsers.add_parser("create-run", help="Create a protocol run.")
    create_run.add_argument("protocol_id", type=int)
    add_action_flags(create_run)
    create_run.set_defaults(handler=handle_create_run)

    load_instr = subparsers.add_parser(
        "load-instructions", help="Get load instructions for the current run."
    )
    load_instr.set_defaults(handler=handle_load_instructions)

    load_done = subparsers.add_parser(
        "load-complete", help="Signal that loading is complete."
    )
    add_action_flags(load_done)
    load_done.set_defaults(handler=handle_load_complete)

    pause = subparsers.add_parser("pause", help="Pause the current run.")
    add_action_flags(pause)
    pause.set_defaults(handler=handle_pause)

    resume = subparsers.add_parser("resume", help="Resume the paused run.")
    add_action_flags(resume)
    resume.set_defaults(handler=handle_resume)

    abort = subparsers.add_parser("abort", help="Abort the current run.")
    add_action_flags(abort)
    abort.set_defaults(handler=handle_abort)

    subparsers.add_parser("rtsa", help="Get real-time step analysis.").set_defaults(
        handler=handle_rtsa
    )

    cleanup = subparsers.add_parser("cleanup", help="Cleanup / unloading after run.")
    add_action_flags(cleanup)
    cleanup.set_defaults(handler=handle_cleanup)

    # ── Run data / results ──────────────────────────────────────────

    subparsers.add_parser("list-run-data", help="List all run data.").set_defaults(
        handler=handle_list_run_data
    )

    get_rd = subparsers.add_parser("get-run-data", help="Get run data by ID.")
    get_rd.add_argument("run_data_id", type=int)
    get_rd.set_defaults(handler=handle_get_run_data)

    # ── Labware ─────────────────────────────────────────────────────

    subparsers.add_parser("list-labware", help="List all labware definitions.").set_defaults(
        handler=handle_list_labware
    )

    get_lw = subparsers.add_parser("get-labware", help="Get labware by ID.")
    get_lw.add_argument("labware_id", type=int)
    get_lw.set_defaults(handler=handle_get_labware)

    get_lw_name = subparsers.add_parser("get-labware-by-name", help="Get labware by name.")
    get_lw_name.add_argument("name")
    get_lw_name.set_defaults(handler=handle_get_labware_by_name)

    subparsers.add_parser(
        "labware-classifications", help="Get labware classifications."
    ).set_defaults(handler=handle_labware_classifications)

    # ── Liquid classes ──────────────────────────────────────────────

    subparsers.add_parser("list-liquid-classes", help="List liquid classes.").set_defaults(
        handler=handle_list_liquid_classes
    )

    # ── Deck ────────────────────────────────────────────────────────

    get_deck = subparsers.add_parser("get-deck", help="Get deck layout for a protocol.")
    get_deck.add_argument("protocol_id", type=int)
    get_deck.set_defaults(handler=handle_get_deck)

    scan_deck = subparsers.add_parser("scan-deck", help="Scan deck for labware.")
    scan_deck.add_argument("--matches", type=int, default=1)
    scan_deck.set_defaults(handler=handle_scan_deck)

    # ── Diagnostics ─────────────────────────────────────────────────

    subparsers.add_parser("diagnostics", help="Get diagnostics info.").set_defaults(
        handler=handle_diagnostics
    )

    diag_transport = subparsers.add_parser(
        "diag-transport", help="Run transport diagnostic."
    )
    add_action_flags(diag_transport)
    diag_transport.set_defaults(handler=handle_diag_transport)

    diag_tip = subparsers.add_parser("diag-tip-pickup", help="Run tip pickup diagnostic.")
    add_action_flags(diag_tip)
    diag_tip.set_defaults(handler=handle_diag_tip)

    diag_pressure = subparsers.add_parser("diag-pressure", help="Run pressure diagnostic.")
    add_action_flags(diag_pressure)
    diag_pressure.set_defaults(handler=handle_diag_pressure)

    diag_drip = subparsers.add_parser("diag-drip", help="Run drip diagnostic.")
    add_action_flags(diag_drip)
    diag_drip.set_defaults(handler=handle_diag_drip)

    # ── Calibration ─────────────────────────────────────────────────

    self_cal = subparsers.add_parser("self-calibration", help="Start self-calibration.")
    add_action_flags(self_cal)
    self_cal.set_defaults(handler=handle_self_calibration)

    subparsers.add_parser("calibration-results", help="Get calibration results.").set_defaults(
        handler=handle_calibration_results
    )

    abort_cal = subparsers.add_parser("abort-calibration", help="Abort calibration.")
    add_action_flags(abort_cal)
    abort_cal.set_defaults(handler=handle_abort_calibration)

    # ── Power ───────────────────────────────────────────────────────

    subparsers.add_parser("is-initialized", help="Check if the instrument is initialized.").set_defaults(
        handler=handle_is_initialized
    )

    powerdown = subparsers.add_parser("request-powerdown", help="Request power-down.")
    add_action_flags(powerdown)
    powerdown.set_defaults(handler=handle_request_powerdown)

    confirm_pd = subparsers.add_parser("confirm-powerdown", help="Confirm power-down.")
    add_action_flags(confirm_pd)
    confirm_pd.set_defaults(handler=handle_confirm_powerdown)

    cancel_pd = subparsers.add_parser("cancel-powerdown", help="Cancel power-down request.")
    cancel_pd.set_defaults(handler=handle_cancel_powerdown)

    # ── HEPA / UV ───────────────────────────────────────────────────

    start_hepa = subparsers.add_parser("start-hepa", help="Start HEPA fan.")
    add_action_flags(start_hepa)
    start_hepa.set_defaults(handler=handle_start_hepa)

    stop_hepa = subparsers.add_parser("stop-hepa", help="Stop HEPA fan.")
    add_action_flags(stop_hepa)
    stop_hepa.set_defaults(handler=handle_stop_hepa)

    subparsers.add_parser("hepa-status", help="Check if HEPA fan is running.").set_defaults(
        handler=handle_hepa_status
    )

    # ── Maintenance ─────────────────────────────────────────────────

    subparsers.add_parser("maintenance", help="Get maintenance info.").set_defaults(
        handler=handle_maintenance
    )

    subparsers.add_parser("channel-counters", help="Get channel counters.").set_defaults(
        handler=handle_channel_counters
    )

    # ── Service / sensors ───────────────────────────────────────────

    subparsers.add_parser("sensor-status", help="Get sensor status.").set_defaults(
        handler=handle_sensor_status
    )

    subparsers.add_parser("door-state", help="Get door state.").set_defaults(
        handler=handle_door_state
    )

    subparsers.add_parser("is-parked", help="Check if instrument is parked.").set_defaults(
        handler=handle_is_parked
    )

    # ── Camera ──────────────────────────────────────────────────────

    subparsers.add_parser("cameras", help="List cameras.").set_defaults(
        handler=handle_cameras
    )

    subparsers.add_parser(
        "vision-status", help="Get vision system status."
    ).set_defaults(handler=handle_vision_status)

    # ── Generic HTTP ────────────────────────────────────────────────

    get_cmd = subparsers.add_parser("get", help="GET any Prep API path.")
    get_cmd.add_argument("path")
    get_cmd.add_argument("--query-json")
    get_cmd.set_defaults(handler=handle_get)

    request = subparsers.add_parser(
        "request",
        help="Run a generic Prep API request. Non-GET methods require confirmation.",
    )
    request.add_argument("method", choices=["GET", "POST", "PUT", "DELETE"])
    request.add_argument("path")
    request.add_argument("--body-json")
    request.add_argument("--body-file", type=Path)
    request.add_argument("--query-json")
    add_action_flags(request)
    request.set_defaults(handler=handle_request)

    return parser


# ── Helpers ─────────────────────────────────────────────────────────


def add_action_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--allow-action",
        action="store_true",
        help="Acknowledge that this command can affect hardware.",
    )
    parser.add_argument(
        "--confirm",
        help=f"Must be set to {CONFIRMATION_PHRASE}.",
    )


def client_from_args(args: argparse.Namespace) -> PrepClient:
    host = args.host
    if host is None:
        print("Error: --host or HAMILTON_HOST is required", file=sys.stderr)
        raise SystemExit(1)
    config = HostConfig(
        hostname=host,
        port=args.port,
        timeout=args.timeout,
        use_https=args.https,
    )
    client = PrepClient(host=config)
    if args.token:
        client._token = args.token
    return client


def _env_int(name: str) -> int | None:
    val = os.environ.get(name)
    return int(val) if val else None


def _load_json_arg(text: str | None = None, path: Path | None = None) -> Any | None:
    if text is not None:
        return json.loads(text)
    if path is not None:
        return json.loads(path.read_text())
    return None


# ── Handlers ────────────────────────────────────────────────────────


def handle_login(args: argparse.Namespace) -> PrepResponse:
    client = client_from_args(args)
    username = args.username
    if not username:
        username = input("Username: ")
    password = args.password
    if not password:
        password = getpass.getpass("Password: ")
    return client.authenticate(username, password)


def handle_check_auth(args: argparse.Namespace) -> PrepResponse:
    return client_from_args(args).check_authentication()


def handle_renew_token(args: argparse.Namespace) -> PrepResponse:
    return client_from_args(args).renew_token()


def handle_logout(args: argparse.Namespace) -> PrepResponse:
    return client_from_args(args).logout()


def handle_system_ready(args: argparse.Namespace) -> PrepResponse:
    return client_from_args(args).get_system_ready()


def handle_software_versions(args: argparse.Namespace) -> PrepResponse:
    return client_from_args(args).get_software_versions()


def handle_environment(args: argparse.Namespace) -> PrepResponse:
    return client_from_args(args).get_environment()


def handle_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    return client_from_args(args).snapshot()


def handle_errors(args: argparse.Namespace) -> PrepResponse:
    return client_from_args(args).get_errors()


def handle_runtime_errors(args: argparse.Namespace) -> PrepResponse:
    return client_from_args(args).get_runtime_errors()


def handle_clear_errors(args: argparse.Namespace) -> PrepResponse:
    require_action_confirmation(args.allow_action, args.confirm)
    return client_from_args(args).clear_errors()


def handle_instruments(args: argparse.Namespace) -> PrepResponse:
    return client_from_args(args).get_instruments()


def handle_connection_status(args: argparse.Namespace) -> PrepResponse:
    return client_from_args(args).get_connection_status()


def handle_run_state(args: argparse.Namespace) -> PrepResponse:
    return client_from_args(args).get_global_run_state()


def handle_serial_number(args: argparse.Namespace) -> PrepResponse:
    return client_from_args(args).get_serial_number()


def handle_initialize(args: argparse.Namespace) -> PrepResponse:
    require_action_confirmation(args.allow_action, args.confirm)
    return client_from_args(args).initialize_instrument()


def handle_use_mock(args: argparse.Namespace) -> PrepResponse:
    require_action_confirmation(args.allow_action, args.confirm)
    return client_from_args(args).use_mock_instrument()


def handle_list_protocols(args: argparse.Namespace) -> PrepResponse:
    return client_from_args(args).list_protocols()


def handle_get_protocol(args: argparse.Namespace) -> PrepResponse:
    return client_from_args(args).get_protocol(args.protocol_id)


def handle_protocol_names(args: argparse.Namespace) -> PrepResponse:
    return client_from_args(args).get_protocol_names()


def handle_verify_protocol(args: argparse.Namespace) -> PrepResponse:
    return client_from_args(args).verify_protocol(args.protocol_id)


def handle_validate_protocol(args: argparse.Namespace) -> PrepResponse:
    return client_from_args(args).validate_protocol(args.protocol_id)


def handle_preview_protocol(args: argparse.Namespace) -> PrepResponse:
    return client_from_args(args).preview_protocol(args.protocol_id)


def handle_import_protocols(args: argparse.Namespace) -> PrepResponse:
    require_action_confirmation(args.allow_action, args.confirm)
    return client_from_args(args).import_protocols(args.file)


def handle_list_steps(args: argparse.Namespace) -> PrepResponse:
    return client_from_args(args).list_steps(args.protocol_id)


def handle_get_step(args: argparse.Namespace) -> PrepResponse:
    return client_from_args(args).get_step(args.protocol_id, args.step_id)


def handle_create_run(args: argparse.Namespace) -> PrepResponse:
    require_action_confirmation(args.allow_action, args.confirm)
    return client_from_args(args).create_run(args.protocol_id)


def handle_load_instructions(args: argparse.Namespace) -> PrepResponse:
    return client_from_args(args).get_load_instructions()


def handle_load_complete(args: argparse.Namespace) -> PrepResponse:
    require_action_confirmation(args.allow_action, args.confirm)
    return client_from_args(args).load_complete()


def handle_pause(args: argparse.Namespace) -> PrepResponse:
    require_action_confirmation(args.allow_action, args.confirm)
    return client_from_args(args).pause_run()


def handle_resume(args: argparse.Namespace) -> PrepResponse:
    require_action_confirmation(args.allow_action, args.confirm)
    return client_from_args(args).resume_run()


def handle_abort(args: argparse.Namespace) -> PrepResponse:
    require_action_confirmation(args.allow_action, args.confirm)
    return client_from_args(args).abort_run()


def handle_rtsa(args: argparse.Namespace) -> PrepResponse:
    return client_from_args(args).get_rtsa()


def handle_cleanup(args: argparse.Namespace) -> PrepResponse:
    require_action_confirmation(args.allow_action, args.confirm)
    return client_from_args(args).cleanup_unloading()


def handle_list_run_data(args: argparse.Namespace) -> PrepResponse:
    return client_from_args(args).list_run_data()


def handle_get_run_data(args: argparse.Namespace) -> PrepResponse:
    return client_from_args(args).get_run_data(args.run_data_id)


def handle_list_labware(args: argparse.Namespace) -> PrepResponse:
    return client_from_args(args).list_labware()


def handle_get_labware(args: argparse.Namespace) -> PrepResponse:
    return client_from_args(args).get_labware(args.labware_id)


def handle_get_labware_by_name(args: argparse.Namespace) -> PrepResponse:
    return client_from_args(args).get_labware_by_name(args.name)


def handle_labware_classifications(args: argparse.Namespace) -> PrepResponse:
    return client_from_args(args).get_labware_classifications()


def handle_list_liquid_classes(args: argparse.Namespace) -> PrepResponse:
    return client_from_args(args).list_liquid_classes()


def handle_get_deck(args: argparse.Namespace) -> PrepResponse:
    return client_from_args(args).get_deck(args.protocol_id)


def handle_scan_deck(args: argparse.Namespace) -> PrepResponse:
    return client_from_args(args).scan_deck(args.matches)


def handle_diagnostics(args: argparse.Namespace) -> PrepResponse:
    return client_from_args(args).get_diagnostics()


def handle_diag_transport(args: argparse.Namespace) -> PrepResponse:
    require_action_confirmation(args.allow_action, args.confirm)
    return client_from_args(args).run_transport_diagnostic()


def handle_diag_tip(args: argparse.Namespace) -> PrepResponse:
    require_action_confirmation(args.allow_action, args.confirm)
    return client_from_args(args).run_tip_pickup_diagnostic()


def handle_diag_pressure(args: argparse.Namespace) -> PrepResponse:
    require_action_confirmation(args.allow_action, args.confirm)
    return client_from_args(args).run_pressure_diagnostic()


def handle_diag_drip(args: argparse.Namespace) -> PrepResponse:
    require_action_confirmation(args.allow_action, args.confirm)
    return client_from_args(args).run_drip_diagnostic()


def handle_self_calibration(args: argparse.Namespace) -> PrepResponse:
    require_action_confirmation(args.allow_action, args.confirm)
    return client_from_args(args).start_self_calibration()


def handle_calibration_results(args: argparse.Namespace) -> PrepResponse:
    return client_from_args(args).get_calibration_results()


def handle_abort_calibration(args: argparse.Namespace) -> PrepResponse:
    require_action_confirmation(args.allow_action, args.confirm)
    return client_from_args(args).abort_calibration()


def handle_is_initialized(args: argparse.Namespace) -> PrepResponse:
    return client_from_args(args).is_initialized()


def handle_request_powerdown(args: argparse.Namespace) -> PrepResponse:
    require_action_confirmation(args.allow_action, args.confirm)
    return client_from_args(args).request_powerdown()


def handle_confirm_powerdown(args: argparse.Namespace) -> PrepResponse:
    require_action_confirmation(args.allow_action, args.confirm)
    return client_from_args(args).confirm_powerdown()


def handle_cancel_powerdown(args: argparse.Namespace) -> PrepResponse:
    return client_from_args(args).cancel_powerdown()


def handle_start_hepa(args: argparse.Namespace) -> PrepResponse:
    require_action_confirmation(args.allow_action, args.confirm)
    return client_from_args(args).start_hepa_fan()


def handle_stop_hepa(args: argparse.Namespace) -> PrepResponse:
    require_action_confirmation(args.allow_action, args.confirm)
    return client_from_args(args).stop_hepa_fan()


def handle_hepa_status(args: argparse.Namespace) -> PrepResponse:
    return client_from_args(args).is_hepa_fan_running()


def handle_maintenance(args: argparse.Namespace) -> PrepResponse:
    return client_from_args(args).get_maintenance()


def handle_channel_counters(args: argparse.Namespace) -> PrepResponse:
    return client_from_args(args).get_channel_counters()


def handle_sensor_status(args: argparse.Namespace) -> PrepResponse:
    return client_from_args(args).get_sensor_status()


def handle_door_state(args: argparse.Namespace) -> PrepResponse:
    return client_from_args(args).get_door_state()


def handle_is_parked(args: argparse.Namespace) -> PrepResponse:
    return client_from_args(args).is_parked()


def handle_cameras(args: argparse.Namespace) -> PrepResponse:
    return client_from_args(args).get_cameras()


def handle_vision_status(args: argparse.Namespace) -> PrepResponse:
    return client_from_args(args).get_vision_system_status()


def handle_get(args: argparse.Namespace) -> PrepResponse:
    query = _load_json_arg(args.query_json)
    return client_from_args(args).get(args.path, query=query)


def handle_request(args: argparse.Namespace) -> PrepResponse:
    if args.method != "GET":
        require_action_confirmation(args.allow_action, args.confirm)
    body = _load_json_arg(args.body_json, getattr(args, "body_file", None))
    query = _load_json_arg(args.query_json)
    return client_from_args(args).request(args.method, args.path, body=body, query=query)
