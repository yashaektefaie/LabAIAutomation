from __future__ import annotations

import contextlib
import io
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from opentrons_tools.cli import main
from opentrons_tools.client import HostConfig, RobotClient
from opentrons_tools.safety import CONFIRMATION_PHRASE


class RecordingHandler(BaseHTTPRequestHandler):
    records: list[dict[str, Any]] = []

    def log_message(self, format: str, *args: Any) -> None:
        return None

    def _record(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""
        self.records.append(
            {
                "method": self.command,
                "path": self.path,
                "headers": dict(self.headers.items()),
                "body": body,
            }
        )
        return body

    def _json(self, body: dict[str, Any], status: int = 200) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        self._record()
        if self.path == "/health":
            self._json({"name": "test-robot", "api_version": "9.0.0"})
        elif self.path == "/server/update/health":
            self._json({"status": "ok"})
        else:
            self._json({"path": self.path})

    def do_POST(self) -> None:
        self._record()
        self._json({"created": True, "path": self.path}, status=201)

    def do_DELETE(self) -> None:
        self._record()
        self._json({}, status=200)


class FakeRobotServer:
    def __enter__(self) -> "FakeRobotServer":
        RecordingHandler.records = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), RecordingHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    @property
    def host(self) -> str:
        return "127.0.0.1"

    @property
    def port(self) -> int:
        return int(self.server.server_port)

    @property
    def records(self) -> list[dict[str, Any]]:
        return RecordingHandler.records


class ClientTests(unittest.TestCase):
    def test_health_uses_opentrons_header(self) -> None:
        with FakeRobotServer() as robot:
            client = RobotClient(HostConfig(robot.host, robot.port))
            response = client.get_health()

            self.assertTrue(response.ok)
            self.assertEqual(response.body["name"], "test-robot")
            self.assertEqual(robot.records[0]["path"], "/health")
            self.assertEqual(robot.records[0]["headers"]["Opentrons-Version"], "3")

    def test_create_run_posts_expected_body(self) -> None:
        with FakeRobotServer() as robot:
            client = RobotClient(HostConfig(robot.host, robot.port))
            response = client.create_run(protocol_id="protocol-id")

            self.assertEqual(response.status, 201)
            record = robot.records[0]
            self.assertEqual(record["path"], "/runs")
            self.assertEqual(
                json.loads(record["body"].decode("utf-8")),
                {"data": {"protocolId": "protocol-id"}},
            )

    def test_home_posts_expected_command_and_waits_by_default(self) -> None:
        with FakeRobotServer() as robot:
            client = RobotClient(HostConfig(robot.host, robot.port))
            response = client.home("run-id")

            self.assertEqual(response.status, 201)
            record = robot.records[0]
            self.assertEqual(
                record["path"], "/runs/run-id/commands?waitUntilComplete=true"
            )
            self.assertEqual(
                json.loads(record["body"].decode("utf-8")),
                {"data": {"commandType": "home", "params": {}}},
            )

    def test_move_mount_posts_expected_command_and_waits_by_default(self) -> None:
        with FakeRobotServer() as robot:
            client = RobotClient(HostConfig(robot.host, robot.port))
            response = client.move_mount(
                "run-id", mount="left", x=200, y=150, z=150, speed=20
            )

            self.assertEqual(response.status, 201)
            record = robot.records[0]
            self.assertEqual(
                record["path"], "/runs/run-id/commands?waitUntilComplete=true"
            )
            self.assertEqual(
                json.loads(record["body"].decode("utf-8")),
                {
                    "data": {
                        "commandType": "robot/moveTo",
                        "params": {
                            "mount": "left",
                            "destination": {"x": 200, "y": 150, "z": 150},
                            "speed": 20,
                        },
                    }
                },
            )

    def test_upload_protocol_uses_multipart_files_field(self) -> None:
        with FakeRobotServer() as robot, tempfile.TemporaryDirectory() as tmpdir:
            protocol = Path(tmpdir) / "protocol.py"
            protocol.write_text("metadata = {}\n")
            client = RobotClient(HostConfig(robot.host, robot.port))

            response = client.upload_protocol([protocol], protocol_key="abc")

            self.assertEqual(response.status, 201)
            record = robot.records[0]
            self.assertEqual(record["path"], "/protocols")
            self.assertIn("multipart/form-data", record["headers"]["Content-Type"])
            body = record["body"].decode("utf-8", errors="replace")
            self.assertIn('name="files"; filename="protocol.py"', body)
            self.assertIn('name="key"', body)
            self.assertIn("abc", body)

    def test_cli_blocks_mutating_request_without_confirmation(self) -> None:
        with FakeRobotServer() as robot:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(
                    [
                        "--host",
                        robot.host,
                        "--port",
                        str(robot.port),
                        "request",
                        "POST",
                        "/runs",
                        "--body-json",
                        '{"data": {}}',
                    ]
                )

            self.assertEqual(code, 3)
            self.assertEqual(robot.records, [])
            payload = json.loads(stdout.getvalue())
            self.assertFalse(payload["ok"])

    def test_cli_allows_mutating_request_with_confirmation(self) -> None:
        with FakeRobotServer() as robot:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(
                    [
                        "--host",
                        robot.host,
                        "--port",
                        str(robot.port),
                        "request",
                        "POST",
                        "/runs",
                        "--body-json",
                        '{"data": {}}',
                        "--allow-action",
                        "--confirm",
                        CONFIRMATION_PHRASE,
                    ]
                )

            self.assertEqual(code, 0)
            self.assertEqual(robot.records[0]["path"], "/runs")
            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["ok"])

    def test_cli_blocks_home_without_confirmation(self) -> None:
        with FakeRobotServer() as robot:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(
                    [
                        "--host",
                        robot.host,
                        "--port",
                        str(robot.port),
                        "home",
                        "run-id",
                    ]
                )

            self.assertEqual(code, 3)
            self.assertEqual(robot.records, [])
            payload = json.loads(stdout.getvalue())
            self.assertFalse(payload["ok"])

    def test_cli_move_mount_posts_expected_body(self) -> None:
        with FakeRobotServer() as robot:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(
                    [
                        "--host",
                        robot.host,
                        "--port",
                        str(robot.port),
                        "move-mount",
                        "run-id",
                        "left",
                        "--x",
                        "200",
                        "--y",
                        "150",
                        "--z",
                        "150",
                        "--allow-action",
                        "--confirm",
                        CONFIRMATION_PHRASE,
                    ]
                )

            self.assertEqual(code, 0)
            self.assertEqual(
                robot.records[0]["path"],
                "/runs/run-id/commands?waitUntilComplete=true",
            )
            body = json.loads(robot.records[0]["body"].decode("utf-8"))
            self.assertEqual(body["data"]["commandType"], "robot/moveTo")
            self.assertEqual(body["data"]["params"]["mount"], "left")
            self.assertEqual(
                body["data"]["params"]["destination"],
                {"x": 200.0, "y": 150.0, "z": 150.0},
            )
            self.assertEqual(body["data"]["params"]["speed"], 20.0)


if __name__ == "__main__":
    unittest.main()
