from __future__ import annotations

import re
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Iterable

from .client import DEFAULT_PORT, HostConfig, RobotClient

MDNS_SERVICE = "_http._tcp.local."


@dataclass(frozen=True)
class DiscoveredRobot:
    name: str
    hostname: str | None
    ip: str
    port: int
    robot_model: str | None = None
    source: str = "unknown"

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "hostname": self.hostname,
            "ip": self.ip,
            "port": self.port,
            "robot_model": self.robot_model,
            "source": self.source,
        }


def probe_hosts(
    hosts: Iterable[str], port: int = DEFAULT_PORT, timeout: float = 3.0
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for host in hosts:
        client = RobotClient(HostConfig(hostname=host, port=port, timeout=timeout))
        health = client.get_health()
        update_health = client.get_server_update_health()
        results.append(
            {
                "host": host,
                "port": port,
                "reachable": health.ok or update_health.ok,
                "health": health.to_jsonable(),
                "server_update_health": update_health.to_jsonable(),
            }
        )
    return results


def discover_mdns(timeout: float = 5.0, port: int = DEFAULT_PORT) -> list[DiscoveredRobot]:
    zeroconf_results = _discover_mdns_with_zeroconf(timeout=timeout, port=port)
    if zeroconf_results is not None:
        return zeroconf_results
    return _discover_mdns_with_dns_sd(timeout=timeout, port=port)


def _discover_mdns_with_zeroconf(
    timeout: float, port: int
) -> list[DiscoveredRobot] | None:
    try:
        from zeroconf import ServiceBrowser, ServiceListener, Zeroconf
    except ImportError:
        return None

    class Listener(ServiceListener):  # type: ignore[misc, valid-type]
        def __init__(self) -> None:
            self.results: list[DiscoveredRobot] = []

        def add_service(self, zc: Any, type_: str, name: str) -> None:
            info = zc.get_service_info(type_, name)
            if info is None or info.port != port:
                return
            addresses = [socket.inet_ntoa(addr) for addr in info.addresses if len(addr) == 4]
            robot_model = None
            for key, value in info.properties.items():
                if key == b"robotModel":
                    robot_model = value.decode("utf-8", errors="replace")
            for ip in addresses:
                self.results.append(
                    DiscoveredRobot(
                        name=name.removesuffix("." + MDNS_SERVICE),
                        hostname=info.server.removesuffix(".") if info.server else None,
                        ip=ip,
                        port=info.port,
                        robot_model=robot_model,
                        source="zeroconf",
                    )
                )

        def update_service(self, zc: Any, type_: str, name: str) -> None:
            self.add_service(zc, type_, name)

        def remove_service(self, zc: Any, type_: str, name: str) -> None:
            return None

    listener = Listener()
    zc = Zeroconf()
    try:
        ServiceBrowser(zc, MDNS_SERVICE, listener)
        time.sleep(timeout)
        return _dedupe(listener.results)
    finally:
        zc.close()


def _discover_mdns_with_dns_sd(timeout: float, port: int) -> list[DiscoveredRobot]:
    if shutil.which("dns-sd") is None:
        return []

    browser = subprocess.Popen(
        ["dns-sd", "-B", "_http._tcp", "local"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        try:
            stdout, _ = browser.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            browser.terminate()
            stdout, _ = browser.communicate(timeout=1)
    finally:
        if browser.poll() is None:
            browser.kill()

    service_names = _parse_dns_sd_browse(stdout)
    results: list[DiscoveredRobot] = []
    for name in service_names:
        resolved = _resolve_dns_sd_service(name, timeout=max(1.0, min(timeout, 3.0)))
        if resolved is not None and resolved.port == port:
            results.append(resolved)
    return _dedupe(results)


def _parse_dns_sd_browse(output: str) -> list[str]:
    names: list[str] = []
    for line in output.splitlines():
        if " Add " not in line or "_http._tcp" not in line:
            continue
        parts = line.split(maxsplit=6)
        if len(parts) >= 7:
            names.append(parts[6].strip())
    return list(dict.fromkeys(names))


def _resolve_dns_sd_service(name: str, timeout: float) -> DiscoveredRobot | None:
    resolver = subprocess.Popen(
        ["dns-sd", "-L", name, "_http._tcp", "local"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        try:
            stdout, _ = resolver.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            resolver.terminate()
            stdout, _ = resolver.communicate(timeout=1)
    finally:
        if resolver.poll() is None:
            resolver.kill()

    reached = re.search(r"can be reached at (?P<host>\S+):(?P<port>\d+)", stdout)
    if reached is None:
        return None
    hostname = reached.group("host").removesuffix(".")
    service_port = int(reached.group("port"))
    robot_model_match = re.search(r"robotModel=(?P<model>[^\s]+)", stdout)
    robot_model = robot_model_match.group("model") if robot_model_match else None

    try:
        ip = socket.gethostbyname(hostname)
    except OSError:
        ip = hostname

    return DiscoveredRobot(
        name=name,
        hostname=hostname,
        ip=ip,
        port=service_port,
        robot_model=robot_model,
        source="dns-sd",
    )


def _dedupe(robots: list[DiscoveredRobot]) -> list[DiscoveredRobot]:
    seen: set[tuple[str, int]] = set()
    deduped: list[DiscoveredRobot] = []
    for robot in robots:
        key = (robot.ip, robot.port)
        if key not in seen:
            seen.add(key)
            deduped.append(robot)
    return deduped
