from __future__ import annotations

import json
import socket
import time
from typing import Any, Callable, Iterable


class NotificationDependencyError(RuntimeError):
    pass


def listen(
    host: str,
    topics: Iterable[str],
    seconds: float,
    on_message: Callable[[dict[str, Any]], None],
    port: int = 1883,
) -> None:
    try:
        import paho.mqtt.client as mqtt
    except ImportError as error:
        listen_with_stdlib(host, topics, seconds, on_message, port=port)
        return

    client = mqtt.Client(
        client_id=f"ot-agent-{int(time.time())}",
        protocol=mqtt.MQTTv5,
    )

    def handle_connect(client: Any, _userdata: Any, _flags: Any, reason_code: Any, _props: Any) -> None:
        if int(reason_code) != 0:
            on_message({"event": "connect_error", "reason_code": int(reason_code)})
            return
        for topic in topics:
            client.subscribe(topic, qos=1)
        on_message({"event": "connected", "host": host, "port": port, "topics": list(topics)})

    def handle_message(_client: Any, _userdata: Any, message: Any) -> None:
        payload = message.payload.decode("utf-8", errors="replace")
        try:
            parsed_payload: Any = json.loads(payload)
        except json.JSONDecodeError:
            parsed_payload = payload
        on_message(
            {
                "event": "message",
                "topic": message.topic,
                "qos": message.qos,
                "payload": parsed_payload,
            }
        )

    client.on_connect = handle_connect
    client.on_message = handle_message
    client.connect(host, port=port, keepalive=60)
    client.loop_start()
    try:
        time.sleep(seconds)
    finally:
        client.loop_stop()
        client.disconnect()


def listen_with_stdlib(
    host: str,
    topics: Iterable[str],
    seconds: float,
    on_message: Callable[[dict[str, Any]], None],
    port: int = 1883,
) -> None:
    topic_list = list(topics)
    client_id = f"ot-agent-{int(time.time())}"
    deadline = time.monotonic() + seconds

    with socket.create_connection((host, port), timeout=min(5.0, max(1.0, seconds))) as sock:
        sock.settimeout(1.0)
        sock.sendall(_encode_connect(client_id))
        packet_type, _flags, payload = _read_packet(sock)
        if packet_type != 2:
            raise NotificationDependencyError("MQTT broker did not return CONNACK.")
        if len(payload) < 2 or payload[1] != 0:
            raise NotificationDependencyError(f"MQTT CONNACK failed: {payload!r}")
        on_message({"event": "connected", "host": host, "port": port, "topics": topic_list})

        if topic_list:
            sock.sendall(_encode_subscribe(1, topic_list))
            packet_type, _flags, payload = _read_packet(sock)
            if packet_type != 9:
                raise NotificationDependencyError("MQTT broker did not return SUBACK.")
            on_message({"event": "subscribed", "topics": topic_list, "payload": list(payload)})

        while time.monotonic() < deadline:
            try:
                packet_type, flags, payload = _read_packet(sock)
            except TimeoutError:
                continue
            except socket.timeout:
                continue
            if packet_type == 3:
                topic, message_payload = _decode_publish(flags, payload)
                try:
                    parsed_payload: Any = json.loads(message_payload)
                except json.JSONDecodeError:
                    parsed_payload = message_payload
                on_message(
                    {
                        "event": "message",
                        "topic": topic,
                        "qos": (flags >> 1) & 0x03,
                        "payload": parsed_payload,
                    }
                )

        sock.sendall(bytes([0xE0, 0x00]))


def _encode_connect(client_id: str) -> bytes:
    variable_header = (
        _utf8("MQTT")
        + bytes([5, 0x02])
        + (60).to_bytes(2, "big")
        + b"\x00"
    )
    payload = _utf8(client_id)
    return _fixed_header(1, 0, len(variable_header) + len(payload)) + variable_header + payload


def _encode_subscribe(packet_id: int, topics: list[str]) -> bytes:
    variable_header = packet_id.to_bytes(2, "big") + b"\x00"
    payload = b"".join(_utf8(topic) + b"\x01" for topic in topics)
    return _fixed_header(8, 2, len(variable_header) + len(payload)) + variable_header + payload


def _decode_publish(flags: int, payload: bytes) -> tuple[str, str]:
    if len(payload) < 2:
        return "", ""
    topic_len = int.from_bytes(payload[:2], "big")
    topic = payload[2 : 2 + topic_len].decode("utf-8", errors="replace")
    index = 2 + topic_len
    qos = (flags >> 1) & 0x03
    if qos > 0:
        index += 2
    message = payload[index:].decode("utf-8", errors="replace")
    return topic, message


def _read_packet(sock: socket.socket) -> tuple[int, int, bytes]:
    first = sock.recv(1)
    if not first:
        raise TimeoutError("MQTT socket closed.")
    byte = first[0]
    remaining = _read_remaining_length(sock)
    payload = _recv_exact(sock, remaining)
    return byte >> 4, byte & 0x0F, payload


def _read_remaining_length(sock: socket.socket) -> int:
    multiplier = 1
    value = 0
    while True:
        encoded = sock.recv(1)
        if not encoded:
            raise TimeoutError("MQTT socket closed while reading length.")
        byte = encoded[0]
        value += (byte & 127) * multiplier
        if byte & 128 == 0:
            return value
        multiplier *= 128
        if multiplier > 128 * 128 * 128:
            raise NotificationDependencyError("Malformed MQTT remaining length.")


def _recv_exact(sock: socket.socket, length: int) -> bytes:
    chunks: list[bytes] = []
    remaining = length
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise TimeoutError("MQTT socket closed while reading payload.")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _fixed_header(packet_type: int, flags: int, remaining_length: int) -> bytes:
    return bytes([(packet_type << 4) | flags]) + _encode_remaining_length(remaining_length)


def _encode_remaining_length(value: int) -> bytes:
    encoded = bytearray()
    while True:
        byte = value % 128
        value //= 128
        if value > 0:
            byte |= 128
        encoded.append(byte)
        if value == 0:
            return bytes(encoded)


def _utf8(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return len(encoded).to_bytes(2, "big") + encoded
