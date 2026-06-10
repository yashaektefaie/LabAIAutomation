from __future__ import annotations

import json
import mimetypes
import secrets
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

DEFAULT_PORT = 31950
DEFAULT_API_VERSION = "3"
USER_AGENT = "opentrons-agent-tools/0.1"


class RobotApiError(RuntimeError):
    def __init__(self, response: "RobotResponse") -> None:
        super().__init__(
            f"Robot API request failed: {response.method} {response.url} "
            f"returned HTTP {response.status}"
        )
        self.response = response


@dataclass(frozen=True)
class RobotResponse:
    method: str
    url: str
    status: int
    reason: str
    headers: dict[str, str]
    body: Any

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "method": self.method,
            "url": self.url,
            "status": self.status,
            "reason": self.reason,
            "headers": self.headers,
            "body": self.body,
        }


@dataclass(frozen=True)
class HostConfig:
    hostname: str
    port: int = DEFAULT_PORT
    token: str | None = None
    timeout: float = 10.0

    @property
    def base_url(self) -> str:
        host = self.hostname
        if ":" in host and not host.startswith("[") and not host.endswith("]"):
            host = f"[{host}]"
        return f"http://{host}:{self.port}"


class RobotClient:
    def __init__(self, host: HostConfig) -> None:
        self.host = host

    def get_health(self) -> RobotResponse:
        return self.get("/health")

    def get_server_update_health(self) -> RobotResponse:
        return self.get("/server/update/health")

    def snapshot(self) -> dict[str, Any]:
        endpoints = {
            "health": "/health",
            "server_update_health": "/server/update/health",
            "protocols": "/protocols",
            "runs": "/runs",
            "modules": "/modules",
            "instruments": "/instruments",
            "calibration_status": "/calibration/status",
            "deck_configuration": "/deck_configuration",
            "settings": "/settings",
            "lights": "/robot/lights",
            "estop_status": "/robot/control/estopStatus",
            "wifi_list": "/wifi/list",
            "system_connections": "/system/connected",
        }
        result: dict[str, Any] = {}
        for name, path in endpoints.items():
            response = self.get(path)
            result[name] = response.to_jsonable()
        return result

    def list_protocols(self) -> RobotResponse:
        return self.get("/protocols")

    def upload_protocol(
        self,
        files: Iterable[Path],
        protocol_key: str | None = None,
        protocol_kind: str | None = None,
        run_time_parameter_values: Mapping[str, Any] | None = None,
        run_time_parameter_files: Mapping[str, Any] | None = None,
    ) -> RobotResponse:
        fields: list[tuple[str, str]] = []
        if protocol_key is not None:
            fields.append(("key", protocol_key))
        if protocol_kind is not None:
            fields.append(("protocolKind", protocol_kind))
        if run_time_parameter_values is not None:
            fields.append(
                ("runTimeParameterValues", json.dumps(run_time_parameter_values))
            )
        if run_time_parameter_files is not None:
            fields.append(("runTimeParameterFiles", json.dumps(run_time_parameter_files)))

        return self.request_multipart(
            "POST",
            "/protocols",
            fields=fields,
            files=[("files", file_path) for file_path in files],
        )

    def create_run(
        self,
        protocol_id: str | None = None,
        labware_offsets: list[Mapping[str, Any]] | None = None,
        run_time_parameter_values: Mapping[str, Any] | None = None,
        run_time_parameter_files: Mapping[str, Any] | None = None,
    ) -> RobotResponse:
        data: dict[str, Any] = {}
        if protocol_id is not None:
            data["protocolId"] = protocol_id
        if labware_offsets is not None:
            data["labwareOffsets"] = labware_offsets
        if run_time_parameter_values is not None:
            data["runTimeParameterValues"] = run_time_parameter_values
        if run_time_parameter_files is not None:
            data["runTimeParameterFiles"] = run_time_parameter_files
        return self.post("/runs", {"data": data})

    def create_run_action(self, run_id: str, action_type: str) -> RobotResponse:
        return self.post(f"/runs/{run_id}/actions", {"data": {"actionType": action_type}})

    def create_run_command(
        self, run_id: str, command: Mapping[str, Any], wait_until_complete: bool = False
    ) -> RobotResponse:
        query = {"waitUntilComplete": str(wait_until_complete).lower()}
        return self.post(f"/runs/{run_id}/commands", {"data": dict(command)}, query=query)

    def home(
        self,
        run_id: str,
        axes: Iterable[str] | None = None,
        wait_until_complete: bool = True,
    ) -> RobotResponse:
        params: dict[str, Any] = {}
        if axes is not None:
            params["axes"] = list(axes)
        return self.create_run_command(
            run_id,
            {"commandType": "home", "params": params},
            wait_until_complete=wait_until_complete,
        )

    def move_mount(
        self,
        run_id: str,
        mount: str,
        x: float,
        y: float,
        z: float,
        speed: float | None = 20.0,
        wait_until_complete: bool = True,
    ) -> RobotResponse:
        params: dict[str, Any] = {
            "mount": mount,
            "destination": {"x": x, "y": y, "z": z},
        }
        if speed is not None:
            params["speed"] = speed
        return self.create_run_command(
            run_id,
            {"commandType": "robot/moveTo", "params": params},
            wait_until_complete=wait_until_complete,
        )

    def delete_run(self, run_id: str) -> RobotResponse:
        return self.delete(f"/runs/{run_id}")

    def create_live_command(
        self, command: Mapping[str, Any], wait_until_complete: bool = False
    ) -> RobotResponse:
        query = {"waitUntilComplete": str(wait_until_complete).lower()}
        return self.post("/commands", {"data": dict(command)}, query=query)

    def get(self, path: str, query: Mapping[str, Any] | None = None) -> RobotResponse:
        return self.request("GET", path, query=query)

    def post(
        self,
        path: str,
        body: Mapping[str, Any] | list[Any] | None = None,
        query: Mapping[str, Any] | None = None,
    ) -> RobotResponse:
        return self.request("POST", path, body=body, query=query)

    def put(
        self,
        path: str,
        body: Mapping[str, Any] | list[Any] | None = None,
        query: Mapping[str, Any] | None = None,
    ) -> RobotResponse:
        return self.request("PUT", path, body=body, query=query)

    def patch(
        self,
        path: str,
        body: Mapping[str, Any] | list[Any] | None = None,
        query: Mapping[str, Any] | None = None,
    ) -> RobotResponse:
        return self.request("PATCH", path, body=body, query=query)

    def delete(
        self,
        path: str,
        body: Mapping[str, Any] | list[Any] | None = None,
        query: Mapping[str, Any] | None = None,
    ) -> RobotResponse:
        return self.request("DELETE", path, body=body, query=query)

    def request(
        self,
        method: str,
        path: str,
        body: Mapping[str, Any] | list[Any] | None = None,
        query: Mapping[str, Any] | None = None,
    ) -> RobotResponse:
        data: bytes | None = None
        headers = self._headers()
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        return self._open(method, self._url(path, query), headers=headers, data=data)

    def request_multipart(
        self,
        method: str,
        path: str,
        fields: Iterable[tuple[str, str]],
        files: Iterable[tuple[str, Path]],
        query: Mapping[str, Any] | None = None,
    ) -> RobotResponse:
        boundary = f"otagent-{secrets.token_hex(16)}"
        body = _encode_multipart(boundary, fields, files)
        headers = self._headers()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        return self._open(method, self._url(path, query), headers=headers, data=body)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Opentrons-Version": DEFAULT_API_VERSION,
            "User-Agent": USER_AGENT,
        }
        if self.host.token is not None:
            headers["authenticationBearer"] = self.host.token
        return headers

    def _url(self, path: str, query: Mapping[str, Any] | None = None) -> str:
        clean_path = path if path.startswith("/") else f"/{path}"
        url = f"{self.host.base_url}{clean_path}"
        if query:
            encoded = urllib.parse.urlencode(
                {key: str(value) for key, value in query.items() if value is not None}
            )
            if encoded:
                url = f"{url}?{encoded}"
        return url

    def _open(
        self, method: str, url: str, headers: Mapping[str, str], data: bytes | None
    ) -> RobotResponse:
        request = urllib.request.Request(
            url=url, data=data, headers=dict(headers), method=method.upper()
        )
        try:
            with urllib.request.urlopen(request, timeout=self.host.timeout) as response:
                return _robot_response(method, url, response.status, response.reason, response)
        except urllib.error.HTTPError as error:
            return _robot_response(method, url, error.code, error.reason, error)
        except urllib.error.URLError as error:
            body = {"message": str(error.reason)}
            return RobotResponse(
                method=method.upper(),
                url=url,
                status=-1,
                reason="URL error",
                headers={},
                body=body,
            )


def raise_for_status(response: RobotResponse) -> RobotResponse:
    if not response.ok:
        raise RobotApiError(response)
    return response


def _robot_response(
    method: str,
    url: str,
    status: int,
    reason: str,
    readable: Any,
) -> RobotResponse:
    raw = readable.read()
    headers = dict(readable.headers.items())
    return RobotResponse(
        method=method.upper(),
        url=url,
        status=status,
        reason=reason,
        headers=headers,
        body=_parse_body(raw, headers.get("Content-Type", "")),
    )


def _parse_body(raw: bytes, content_type: str) -> Any:
    if not raw:
        return None
    text = raw.decode("utf-8", errors="replace")
    if "json" in content_type.lower():
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _encode_multipart(
    boundary: str,
    fields: Iterable[tuple[str, str]],
    files: Iterable[tuple[str, Path]],
) -> bytes:
    chunks: list[bytes] = []
    boundary_bytes = boundary.encode("ascii")

    def add_line(line: bytes = b"") -> None:
        chunks.append(line + b"\r\n")

    for name, value in fields:
        add_line(b"--" + boundary_bytes)
        add_line(f'Content-Disposition: form-data; name="{name}"'.encode("utf-8"))
        add_line()
        add_line(str(value).encode("utf-8"))

    for name, file_path in files:
        path = Path(file_path)
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        add_line(b"--" + boundary_bytes)
        add_line(
            (
                f'Content-Disposition: form-data; name="{name}"; '
                f'filename="{path.name}"'
            ).encode("utf-8")
        )
        add_line(f"Content-Type: {content_type}".encode("utf-8"))
        add_line()
        chunks.append(path.read_bytes())
        chunks.append(b"\r\n")

    add_line(b"--" + boundary_bytes + b"--")
    return b"".join(chunks)
