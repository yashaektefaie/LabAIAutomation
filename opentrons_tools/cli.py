from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from .client import DEFAULT_PORT, HostConfig, RobotClient, RobotResponse
from .discovery import discover_mdns, probe_hosts
from .notifications import NotificationDependencyError, listen
from .output import emit_json
from .safety import CONFIRMATION_PHRASE, SafetyError, require_action_confirmation

MOUNTS = ("left", "right", "extension")
MOTOR_AXES = (
    "x",
    "y",
    "leftZ",
    "rightZ",
    "leftPlunger",
    "rightPlunger",
    "extensionZ",
    "extensionJaw",
    "axis96ChannelCam",
)


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
    except NotificationDependencyError as error:
        emit_json({"ok": False, "error": str(error)})
        return 3
    except KeyboardInterrupt:
        emit_json({"ok": False, "error": "Interrupted"})
        return 130

    if isinstance(result, RobotResponse):
        emit_json(result.to_jsonable())
        return 0 if result.ok else 2
    emit_json(result)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ot-tools",
        description="Agent-friendly Opentrons robot tools.",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("OT_HOST"),
        help="Robot hostname/IP. Can also be set with OT_HOST.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("OT_PORT", DEFAULT_PORT)),
        help=f"Robot HTTP API port. Default: {DEFAULT_PORT}.",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("OT_TOKEN"),
        help="Optional authentication bearer token. Can also be set with OT_TOKEN.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("OT_TIMEOUT", "10")),
        help="HTTP timeout in seconds.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    discover = subparsers.add_parser("discover-mdns", help="Find robots via mDNS.")
    discover.add_argument("--seconds", type=float, default=5.0)
    discover.set_defaults(handler=handle_discover_mdns)

    probe = subparsers.add_parser("probe", help="Probe explicit robot hosts.")
    probe.add_argument("hosts", nargs="+")
    probe.set_defaults(handler=handle_probe)

    health = subparsers.add_parser("health", help="Read /health and update health.")
    health.set_defaults(handler=handle_health)

    snapshot = subparsers.add_parser(
        "snapshot", help="Read a broad non-mutating status snapshot."
    )
    snapshot.set_defaults(handler=handle_snapshot)

    get = subparsers.add_parser("get", help="GET any robot API path.")
    get.add_argument("path")
    get.add_argument("--query-json")
    get.add_argument("--query-file", type=Path)
    get.set_defaults(handler=handle_get)

    request = subparsers.add_parser(
        "request",
        help="Run a generic robot API request. Non-GET methods require confirmation.",
    )
    request.add_argument("method", choices=["GET", "POST", "PUT", "PATCH", "DELETE"])
    request.add_argument("path")
    request.add_argument("--body-json")
    request.add_argument("--body-file", type=Path)
    request.add_argument("--query-json")
    request.add_argument("--query-file", type=Path)
    add_action_flags(request)
    request.set_defaults(handler=handle_request)

    upload = subparsers.add_parser("upload-protocol", help="POST files to /protocols.")
    upload.add_argument("files", nargs="+", type=Path)
    upload.add_argument("--key")
    upload.add_argument("--kind")
    upload.add_argument("--run-time-values-json")
    upload.add_argument("--run-time-values-file", type=Path)
    upload.add_argument("--run-time-files-json")
    upload.add_argument("--run-time-files-file", type=Path)
    add_action_flags(upload)
    upload.set_defaults(handler=handle_upload_protocol)

    create_run = subparsers.add_parser("create-run", help="POST /runs.")
    create_run.add_argument("--protocol-id")
    create_run.add_argument("--labware-offsets-json")
    create_run.add_argument("--labware-offsets-file", type=Path)
    create_run.add_argument("--run-time-values-json")
    create_run.add_argument("--run-time-values-file", type=Path)
    create_run.add_argument("--run-time-files-json")
    create_run.add_argument("--run-time-files-file", type=Path)
    add_action_flags(create_run)
    create_run.set_defaults(handler=handle_create_run)

    run_action = subparsers.add_parser(
        "run-action", help="POST /runs/{id}/actions, e.g. play, pause, stop."
    )
    run_action.add_argument("run_id")
    run_action.add_argument("action_type")
    add_action_flags(run_action)
    run_action.set_defaults(handler=handle_run_action)

    run_command = subparsers.add_parser(
        "run-command", help="POST /runs/{id}/commands."
    )
    run_command.add_argument("run_id")
    run_command.add_argument("--command-json")
    run_command.add_argument("--command-file", type=Path)
    run_command.add_argument("--wait", action="store_true")
    add_action_flags(run_command)
    run_command.set_defaults(handler=handle_run_command)

    home = subparsers.add_parser(
        "home", help="Create a home command in a run. Waits by default."
    )
    home.add_argument("run_id")
    home.add_argument(
        "--axis",
        action="append",
        choices=MOTOR_AXES,
        help="Axis to home. Repeatable. Omit to home all motors.",
    )
    home.add_argument("--no-wait", action="store_true")
    add_action_flags(home)
    home.set_defaults(handler=handle_home)

    move_mount = subparsers.add_parser(
        "move-mount",
        help="Move a mount to an absolute deck-space coordinate. Waits by default.",
    )
    move_mount.add_argument("run_id")
    move_mount.add_argument("mount", choices=MOUNTS)
    move_mount.add_argument("--x", type=float, required=True)
    move_mount.add_argument("--y", type=float, required=True)
    move_mount.add_argument("--z", type=float, required=True)
    move_mount.add_argument(
        "--speed",
        type=float,
        default=20.0,
        help="Max movement speed in mm/s. Default: 20.",
    )
    move_mount.add_argument("--no-wait", action="store_true")
    add_action_flags(move_mount)
    move_mount.set_defaults(handler=handle_move_mount)

    delete_run = subparsers.add_parser("delete-run", help="DELETE /runs/{id}.")
    delete_run.add_argument("run_id")
    add_action_flags(delete_run)
    delete_run.set_defaults(handler=handle_delete_run)

    live_command = subparsers.add_parser("live-command", help="POST /commands.")
    live_command.add_argument("--command-json")
    live_command.add_argument("--command-file", type=Path)
    live_command.add_argument("--wait", action="store_true")
    add_action_flags(live_command)
    live_command.set_defaults(handler=handle_live_command)

    mqtt = subparsers.add_parser("mqtt-listen", help="Listen to robot MQTT topics.")
    mqtt.add_argument(
        "--topic",
        action="append",
        default=[],
        help="MQTT topic. Repeatable. Defaults to robot-server/runs.",
    )
    mqtt.add_argument("--seconds", type=float, default=10.0)
    mqtt.add_argument("--mqtt-port", type=int, default=1883)
    mqtt.set_defaults(handler=handle_mqtt_listen)

    return parser


def add_action_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--allow-action", action="store_true")
    parser.add_argument(
        "--confirm",
        help=f"Required phrase for mutating commands: {CONFIRMATION_PHRASE}",
    )


def client_from_args(args: argparse.Namespace) -> RobotClient:
    if args.host is None:
        raise SafetyError("Missing --host or OT_HOST.")
    return RobotClient(
        HostConfig(
            hostname=args.host,
            port=args.port,
            token=args.token,
            timeout=args.timeout,
        )
    )


def handle_discover_mdns(args: argparse.Namespace) -> dict[str, Any]:
    robots = discover_mdns(timeout=args.seconds, port=args.port)
    return {"ok": True, "robots": [robot.to_jsonable() for robot in robots]}


def handle_probe(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "ok": True,
        "results": probe_hosts(args.hosts, port=args.port, timeout=args.timeout),
    }


def handle_health(args: argparse.Namespace) -> dict[str, Any]:
    client = client_from_args(args)
    health = client.get_health()
    update_health = client.get_server_update_health()
    return {
        "ok": health.ok or update_health.ok,
        "health": health.to_jsonable(),
        "server_update_health": update_health.to_jsonable(),
    }


def handle_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    client = client_from_args(args)
    snapshot = client.snapshot()
    return {"ok": True, "snapshot": snapshot}


def handle_get(args: argparse.Namespace) -> RobotResponse:
    client = client_from_args(args)
    query = load_json(args.query_json, args.query_file, default=None)
    return client.get(args.path, query=query)


def handle_request(args: argparse.Namespace) -> RobotResponse:
    if args.method != "GET":
        require_action_confirmation(args.allow_action, args.confirm)
    client = client_from_args(args)
    body = load_json(args.body_json, args.body_file, default=None)
    query = load_json(args.query_json, args.query_file, default=None)
    method = args.method
    return {
        "GET": client.get,
        "POST": client.post,
        "PUT": client.put,
        "PATCH": client.patch,
        "DELETE": client.delete,
    }[method](args.path, body=body, query=query) if method != "GET" else client.get(args.path, query=query)


def handle_upload_protocol(args: argparse.Namespace) -> RobotResponse:
    require_action_confirmation(args.allow_action, args.confirm)
    files = [file_path.expanduser().resolve() for file_path in args.files]
    for file_path in files:
        if not file_path.exists():
            raise FileNotFoundError(str(file_path))
    client = client_from_args(args)
    return client.upload_protocol(
        files,
        protocol_key=args.key,
        protocol_kind=args.kind,
        run_time_parameter_values=load_json(
            args.run_time_values_json, args.run_time_values_file, default=None
        ),
        run_time_parameter_files=load_json(
            args.run_time_files_json, args.run_time_files_file, default=None
        ),
    )


def handle_create_run(args: argparse.Namespace) -> RobotResponse:
    require_action_confirmation(args.allow_action, args.confirm)
    client = client_from_args(args)
    return client.create_run(
        protocol_id=args.protocol_id,
        labware_offsets=load_json(
            args.labware_offsets_json, args.labware_offsets_file, default=None
        ),
        run_time_parameter_values=load_json(
            args.run_time_values_json, args.run_time_values_file, default=None
        ),
        run_time_parameter_files=load_json(
            args.run_time_files_json, args.run_time_files_file, default=None
        ),
    )


def handle_run_action(args: argparse.Namespace) -> RobotResponse:
    require_action_confirmation(args.allow_action, args.confirm)
    client = client_from_args(args)
    return client.create_run_action(args.run_id, args.action_type)


def handle_run_command(args: argparse.Namespace) -> RobotResponse:
    require_action_confirmation(args.allow_action, args.confirm)
    command = load_required_json(args.command_json, args.command_file, "--command-json")
    client = client_from_args(args)
    return client.create_run_command(args.run_id, command, wait_until_complete=args.wait)


def handle_home(args: argparse.Namespace) -> RobotResponse:
    require_action_confirmation(args.allow_action, args.confirm)
    client = client_from_args(args)
    return client.home(
        args.run_id,
        axes=args.axis,
        wait_until_complete=not args.no_wait,
    )


def handle_move_mount(args: argparse.Namespace) -> RobotResponse:
    require_action_confirmation(args.allow_action, args.confirm)
    if args.speed <= 0:
        raise SafetyError("--speed must be greater than 0.")
    client = client_from_args(args)
    return client.move_mount(
        args.run_id,
        mount=args.mount,
        x=args.x,
        y=args.y,
        z=args.z,
        speed=args.speed,
        wait_until_complete=not args.no_wait,
    )


def handle_delete_run(args: argparse.Namespace) -> RobotResponse:
    require_action_confirmation(args.allow_action, args.confirm)
    client = client_from_args(args)
    return client.delete_run(args.run_id)


def handle_live_command(args: argparse.Namespace) -> RobotResponse:
    require_action_confirmation(args.allow_action, args.confirm)
    command = load_required_json(args.command_json, args.command_file, "--command-json")
    client = client_from_args(args)
    return client.create_live_command(command, wait_until_complete=args.wait)


def handle_mqtt_listen(args: argparse.Namespace) -> dict[str, Any]:
    if args.host is None:
        raise SafetyError("Missing --host or OT_HOST.")
    topics = args.topic or ["robot-server/runs"]
    messages: list[dict[str, Any]] = []
    listen(args.host, topics, args.seconds, messages.append, port=args.mqtt_port)
    return {"ok": True, "messages": messages}


def load_required_json(
    json_text: str | None, json_file: Path | None, flag_name: str
) -> dict[str, Any]:
    value = load_json(json_text, json_file, default=None)
    if value is None:
        raise SafetyError(f"Missing {flag_name} or matching file flag.")
    if not isinstance(value, dict):
        raise SafetyError("Expected a JSON object.")
    return value


def load_json(
    json_text: str | None,
    json_file: Path | None,
    default: Any,
) -> Any:
    if json_text is not None and json_file is not None:
        raise SafetyError("Pass JSON either inline or as a file, not both.")
    if json_text is None and json_file is None:
        return default
    if json_file is not None:
        return json.loads(json_file.expanduser().read_text())
    return json.loads(json_text or "null")


if __name__ == "__main__":
    sys.exit(main())
