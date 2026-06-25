from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

USER_AGENT = "hamilton-agent-tools/0.1"

RUN_STATES = {
    0: "NotInitialized",
    1: "Initialized",
    2: "Running",
    3: "Aborting",
    4: "Aborted",
    5: "Processed",
    6: "Pausing",
    7: "Paused",
    8: "Starting",
    9: "Terminating",
    10: "Terminated",
    11: "Unknown",
}


class PrepApiError(RuntimeError):
    def __init__(self, response: "PrepResponse") -> None:
        super().__init__(
            f"Prep API request failed: {response.method} {response.url} "
            f"returned HTTP {response.status}"
        )
        self.response = response


@dataclass(frozen=True)
class PrepResponse:
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
    port: int | None = None
    timeout: float = 10.0
    use_https: bool = False

    @property
    def base_url(self) -> str:
        scheme = "https" if self.use_https else "http"
        host = self.hostname
        if ":" in host and not host.startswith("[") and not host.endswith("]"):
            host = f"[{host}]"
        if self.port is not None:
            return f"{scheme}://{host}:{self.port}"
        return f"{scheme}://{host}"


@dataclass
class PrepClient:
    """HTTP client for the Hamilton Microlab Prep REST API."""

    host: HostConfig
    _token: str | None = field(default=None, repr=False)

    @property
    def authenticated(self) -> bool:
        return self._token is not None

    # ── Authentication ──────────────────────────────────────────────

    def authenticate(self, username: str, password: str) -> PrepResponse:
        resp = self.post(
            "/api/v1/authenticate",
            {"userName": username, "password": password},
            skip_auth=True,
        )
        if resp.ok and isinstance(resp.body, dict):
            self._token = resp.body.get("token")
        return resp

    def renew_token(self) -> PrepResponse:
        resp = self.post("/api/v1/authenticate/renew-token")
        if resp.ok and isinstance(resp.body, dict):
            self._token = resp.body.get("token")
        return resp

    def check_authentication(self) -> PrepResponse:
        return self.get("/api/v1/authenticate/check-authentication")

    def logout(self) -> PrepResponse:
        resp = self.delete("/api/v1/authenticate")
        if resp.ok:
            self._token = None
        return resp

    # ── Instrument status ───────────────────────────────────────────

    def get_instruments(self) -> PrepResponse:
        return self.get("/api/v1/instruments")

    def get_all_available_instruments(self) -> PrepResponse:
        return self.get("/api/v1/instruments/all-available")

    def get_connection_status(self) -> PrepResponse:
        return self.get("/api/v1/instruments/connection-status")

    def get_connection_info(self) -> PrepResponse:
        return self.get("/api/v1/instruments/connection-info")

    def get_active_system(self) -> PrepResponse:
        return self.get("/api/v1/instruments/get-active-system")

    def get_global_run_state(self) -> PrepResponse:
        return self.get("/api/v1/instruments/global-run-state")

    def get_serial_number(self) -> PrepResponse:
        return self.get("/api/v1/instruments/serial-number")

    def initialize_instrument(self) -> PrepResponse:
        return self.post("/api/v1/instruments/initialize")

    def connect_to_instrument(self, body: Mapping[str, Any] | None = None) -> PrepResponse:
        return self.post("/api/v1/instruments/connect-to-instrument", body)

    def use_mock_instrument(self) -> PrepResponse:
        return self.post("/api/v1/instruments/mock")

    # ── System health ───────────────────────────────────────────────

    def get_system_ready(self) -> PrepResponse:
        return self.get("/api/v1/system-ready")

    def get_software_versions(self) -> PrepResponse:
        return self.get("/api/v1/software-versions")

    def get_environment(self) -> PrepResponse:
        return self.get("/api/v1/environment")

    def get_errors(self) -> PrepResponse:
        return self.get("/api/v1/errors")

    def get_runtime_errors(self) -> PrepResponse:
        return self.get("/api/v1/errors/runtime")

    def check_pending_errors(self) -> PrepResponse:
        return self.get("/api/v1/errors/check-for-pending-errors")

    def clear_errors(self) -> PrepResponse:
        return self.post("/api/v1/errors/clear-errors")

    # ── Power ───────────────────────────────────────────────────────

    def is_initialized(self) -> PrepResponse:
        return self.get("/api/v1/power/is-initialized")

    def request_powerdown(self) -> PrepResponse:
        return self.post("/api/v1/power/request-powerdown")

    def confirm_powerdown(self) -> PrepResponse:
        return self.post("/api/v1/power/confirm-powerdown")

    def cancel_powerdown(self) -> PrepResponse:
        return self.post("/api/v1/power/cancel-powerdown")

    # ── Service / sensors ───────────────────────────────────────────

    def get_sensor_status(self) -> PrepResponse:
        return self.get("/api/v1/service-software-api/sensor-status")

    def get_door_state(self) -> PrepResponse:
        return self.get("/api/v1/service-software-api/doorstate")

    def is_parked(self) -> PrepResponse:
        return self.get("/api/v1/service-software-api/is-parked")

    # ── Protocols ───────────────────────────────────────────────────

    def list_protocols(self) -> PrepResponse:
        return self.get("/api/v1/protocols")

    def get_protocol(self, protocol_id: int) -> PrepResponse:
        return self.get(f"/api/v1/protocols/{protocol_id}")

    def get_protocol_names(self) -> PrepResponse:
        return self.get("/api/v1/protocols/names")

    def get_step_types(self) -> PrepResponse:
        return self.get("/api/v1/protocols/properties/step-types")

    def create_protocol(self, body: Mapping[str, Any]) -> PrepResponse:
        return self.post("/api/v1/protocols", body)

    def verify_protocol(self, protocol_id: int) -> PrepResponse:
        return self.get(f"/api/v1/protocols/verify/{protocol_id}")

    def validate_protocol(self, protocol_id: int) -> PrepResponse:
        return self.get(f"/api/v1/protocols/validate/{protocol_id}")

    def preview_protocol(self, protocol_id: int) -> PrepResponse:
        return self.get(f"/api/v1/protocols/preview/{protocol_id}")

    def import_protocols(self, file_path: Path) -> PrepResponse:
        return self._upload_file("POST", "/api/v1/protocols/import", file_path)

    def export_protocols(self) -> PrepResponse:
        return self.get("/api/v1/protocols/export")

    # ── Protocol steps ──────────────────────────────────────────────

    def list_steps(self, protocol_id: int) -> PrepResponse:
        return self.get(f"/api/v1/protocols/{protocol_id}/step")

    def get_step(self, protocol_id: int, step_id: int) -> PrepResponse:
        return self.get(f"/api/v1/protocols/{protocol_id}/step/{step_id}")

    def create_step(self, protocol_id: int, body: Mapping[str, Any]) -> PrepResponse:
        return self.post(f"/api/v1/protocols/{protocol_id}/step", body)

    def update_step(self, protocol_id: int, step_id: int, body: Mapping[str, Any]) -> PrepResponse:
        return self.put(f"/api/v1/protocols/{protocol_id}/step/{step_id}", body)

    def delete_step(self, protocol_id: int, step_id: int) -> PrepResponse:
        return self.delete(f"/api/v1/protocols/{protocol_id}/step/{step_id}")

    # ── Protocol run ────────────────────────────────────────────────

    def create_run(self, protocol_id: int) -> PrepResponse:
        return self.post("/api/v1/protocol-run/create", {"protocolId": protocol_id})

    def get_load_instructions(self) -> PrepResponse:
        return self.get("/api/v1/protocol-run/load-instructions")

    def load_complete(self) -> PrepResponse:
        return self.post("/api/v1/protocol-run/load-complete")

    def pause_run(self) -> PrepResponse:
        return self.post("/api/v1/protocol-run/pause")

    def resume_run(self) -> PrepResponse:
        return self.post("/api/v1/protocol-run/resume")

    def abort_run(self) -> PrepResponse:
        return self.post("/api/v1/protocol-run/abort")

    def get_rtsa(self) -> PrepResponse:
        return self.get("/api/v1/protocol-run/rtsa")

    def get_simulation_speed(self) -> PrepResponse:
        return self.get("/api/v1/protocol-run/simulation-speed")

    def submit_barcodes(self, protocol_id: int, barcodes: list[Mapping[str, Any]]) -> PrepResponse:
        return self.post(
            "/api/v1/protocol-run/submit-barcodes",
            {"protocolId": protocol_id, "barcodes": list(barcodes)},
        )

    def cleanup_unloading(self) -> PrepResponse:
        return self.post("/api/v1/protocol-run/cleanup-unloading")

    # ── Run data / results ──────────────────────────────────────────

    def list_run_data(self) -> PrepResponse:
        return self.get("/api/v1/run-data")

    def get_run_data(self, run_data_id: int) -> PrepResponse:
        return self.get(f"/api/v1/run-data/{run_data_id}")

    def get_run_pdf(self, run_data_id: int) -> PrepResponse:
        return self.get(f"/api/v1/run-data/{run_data_id}/pdf")

    def get_run_pipetting_csv(self, run_data_id: int) -> PrepResponse:
        return self.get(f"/api/v1/run-data/{run_data_id}/pipetting-csv")

    # ── Labware ─────────────────────────────────────────────────────

    def list_labware(self) -> PrepResponse:
        return self.get("/api/v1/labware")

    def get_labware(self, labware_id: int) -> PrepResponse:
        return self.get(f"/api/v1/labware/{labware_id}")

    def get_labware_by_name(self, name: str) -> PrepResponse:
        return self.get(f"/api/v1/labware/by-name/{name}")

    def get_labware_classifications(self) -> PrepResponse:
        return self.get("/api/v1/labware/properties/classifications")

    # ── Liquid classes ──────────────────────────────────────────────

    def list_liquid_classes(self) -> PrepResponse:
        return self.get("/api/v1/liquid-classes")

    def get_liquid_class_settings(self) -> PrepResponse:
        return self.get("/api/v1/liquid-classes/settings")

    # ── Deck ────────────────────────────────────────────────────────

    def get_deck(self, protocol_id: int) -> PrepResponse:
        return self.get(f"/api/v1/deck/{protocol_id}")

    def scan_deck(self, num_matches: int = 1) -> PrepResponse:
        return self.get(f"/api/v1/deck/scan/{num_matches}")

    def calibrate_deck(self) -> PrepResponse:
        return self.post("/api/v1/deck/calibrate")

    # ── Diagnostics ─────────────────────────────────────────────────

    def get_diagnostics(self) -> PrepResponse:
        return self.get("/api/v1/diagnostics")

    def run_transport_diagnostic(self) -> PrepResponse:
        return self.post("/api/v1/diagnostics/instrument/transport")

    def run_tip_pickup_diagnostic(self) -> PrepResponse:
        return self.post("/api/v1/diagnostics/instrument/tip-pickup")

    def run_pressure_diagnostic(self) -> PrepResponse:
        return self.post("/api/v1/diagnostics/instrument/pressure")

    def run_drip_diagnostic(self) -> PrepResponse:
        return self.post("/api/v1/diagnostics/instrument/drip")

    # ── Calibration ─────────────────────────────────────────────────

    def start_self_calibration(self) -> PrepResponse:
        return self.post("/api/v1/calibration/self-calibration")

    def get_calibration_results(self) -> PrepResponse:
        return self.get("/api/v1/calibration/channel-results")

    def abort_calibration(self) -> PrepResponse:
        return self.post("/api/v1/calibration/abort")

    # ── Maintenance ─────────────────────────────────────────────────

    def get_maintenance(self) -> PrepResponse:
        return self.get("/api/v1/maintenance")

    def get_channel_counters(self) -> PrepResponse:
        return self.get("/api/v1/maintenance/channel-counters")

    def reset_channel_counter(self, channel: int) -> PrepResponse:
        return self.post(f"/api/v1/maintenance/reset-channel-counters/{channel}")

    # ── HEPA / UV ───────────────────────────────────────────────────

    def start_hepa_fan(self) -> PrepResponse:
        return self.post("/api/v1/hepa-uv/start-hepa-fan")

    def stop_hepa_fan(self) -> PrepResponse:
        return self.post("/api/v1/hepa-uv/stop-hepa-fan")

    def is_hepa_fan_running(self) -> PrepResponse:
        return self.get("/api/v1/hepa-uv/is-hepa-fan-running")

    def get_hepa_filter_pressure(self) -> PrepResponse:
        return self.get("/api/v1/hepa-uv/hepa-filter-pressure")

    # ── Camera ──────────────────────────────────────────────────────

    def capture_frame(self, rectify: bool = True) -> PrepResponse:
        return self.get(f"/api/v1/camera/{str(rectify).lower()}")

    def get_vision_system_status(self) -> PrepResponse:
        return self.get("/api/v1/camera/vision-system-status")

    def get_cameras(self) -> PrepResponse:
        return self.get("/api/v1/camera/cameras")

    # ── Enclosure / lighting ────────────────────────────────────────

    def get_enclosure(self) -> PrepResponse:
        return self.get("/api/v1/enclosure")

    def set_custom_lighting(self, body: Mapping[str, Any]) -> PrepResponse:
        return self.post("/api/v1/enclosure/set-custom-lighting", body)

    def set_automatic_lighting(self) -> PrepResponse:
        return self.post("/api/v1/enclosure/set-automatic-lighting")

    # ── Thermal control ─────────────────────────────────────────────

    def start_temperature_control(self, body: Mapping[str, Any]) -> PrepResponse:
        return self.put("/api/v1/thermal-device/hhc/start-temperature-control", body)

    def stop_temperature_control(self) -> PrepResponse:
        return self.put("/api/v1/thermal-device/hhc/stop-temperature-control")

    def get_temperature_status(self) -> PrepResponse:
        return self.put("/api/v1/thermal-device/hhc/temperature-status")

    # ── Generic HTTP verbs ──────────────────────────────────────────

    def get(self, path: str, query: Mapping[str, Any] | None = None) -> PrepResponse:
        return self.request("GET", path, query=query)

    def post(
        self,
        path: str,
        body: Mapping[str, Any] | list[Any] | None = None,
        query: Mapping[str, Any] | None = None,
        *,
        skip_auth: bool = False,
    ) -> PrepResponse:
        return self.request("POST", path, body=body, query=query, skip_auth=skip_auth)

    def put(
        self,
        path: str,
        body: Mapping[str, Any] | list[Any] | None = None,
        query: Mapping[str, Any] | None = None,
    ) -> PrepResponse:
        return self.request("PUT", path, body=body, query=query)

    def delete(
        self,
        path: str,
        body: Mapping[str, Any] | list[Any] | None = None,
        query: Mapping[str, Any] | None = None,
    ) -> PrepResponse:
        return self.request("DELETE", path, body=body, query=query)

    def request(
        self,
        method: str,
        path: str,
        body: Mapping[str, Any] | list[Any] | None = None,
        query: Mapping[str, Any] | None = None,
        *,
        skip_auth: bool = False,
    ) -> PrepResponse:
        data: bytes | None = None
        headers = self._headers(skip_auth=skip_auth)
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        return self._open(method, self._url(path, query), headers=headers, data=data)

    def snapshot(self) -> dict[str, Any]:
        endpoints = {
            "system_ready": "/api/v1/system-ready",
            "software_versions": "/api/v1/software-versions",
            "connection_status": "/api/v1/instruments/connection-status",
            "instruments": "/api/v1/instruments",
            "global_run_state": "/api/v1/instruments/global-run-state",
            "active_system": "/api/v1/instruments/get-active-system",
            "is_initialized": "/api/v1/power/is-initialized",
            "errors": "/api/v1/errors",
            "environment": "/api/v1/environment",
            "protocols": "/api/v1/protocols",
            "labware": "/api/v1/labware",
            "diagnostics": "/api/v1/diagnostics",
        }
        result: dict[str, Any] = {}
        for name, path in endpoints.items():
            response = self.get(path)
            result[name] = response.to_jsonable()
        return result

    # ── File upload helper ──────────────────────────────────────────

    def _upload_file(self, method: str, path: str, file_path: Path) -> PrepResponse:
        import mimetypes
        import secrets

        boundary = f"hamilton-{secrets.token_hex(16)}"
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"

        chunks: list[bytes] = []
        boundary_bytes = boundary.encode("ascii")
        chunks.append(b"--" + boundary_bytes + b"\r\n")
        chunks.append(
            f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'.encode()
        )
        chunks.append(f"Content-Type: {content_type}\r\n".encode())
        chunks.append(b"\r\n")
        chunks.append(file_path.read_bytes())
        chunks.append(b"\r\n")
        chunks.append(b"--" + boundary_bytes + b"--\r\n")

        headers = self._headers()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        return self._open(method, self._url(path), headers=headers, data=b"".join(chunks))

    # ── Internal ────────────────────────────────────────────────────

    def _headers(self, *, skip_auth: bool = False) -> dict[str, str]:
        headers: dict[str, str] = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
        if not skip_auth and self._token is not None:
            headers["Authorization"] = f"Bearer {self._token}"
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
    ) -> PrepResponse:
        request = urllib.request.Request(
            url=url, data=data, headers=dict(headers), method=method.upper()
        )
        try:
            with urllib.request.urlopen(request, timeout=self.host.timeout) as response:
                return _prep_response(method, url, response.status, response.reason, response)
        except urllib.error.HTTPError as error:
            return _prep_response(method, url, error.code, error.reason, error)
        except urllib.error.URLError as error:
            body = {"message": str(error.reason)}
            return PrepResponse(
                method=method.upper(),
                url=url,
                status=-1,
                reason="URL error",
                headers={},
                body=body,
            )


def raise_for_status(response: PrepResponse) -> PrepResponse:
    if not response.ok:
        raise PrepApiError(response)
    return response


def _prep_response(
    method: str,
    url: str,
    status: int,
    reason: str,
    readable: Any,
) -> PrepResponse:
    raw = readable.read()
    headers = dict(readable.headers.items())
    return PrepResponse(
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
