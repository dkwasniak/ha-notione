#!/usr/bin/env python3
"""Start and inspect notiOne LIVE mode using the mobile app WebSocket API.

This tool uses only the Python standard library. LIVE mode increases device
power usage, so the state-changing request requires the explicit --start-live
flag.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import os
import socket
import ssl
import struct
import sys
import time
import urllib.error
import urllib.request


LOGIN_URL = "https://auth.notinote.me/public/user/authorize/login"
DEVICELIST_URL = "https://api.notinote.me/secured/internal/devicelist"
WS_HOST = "api.notinote.me"
WS_PORT = 444
WS_PATH = "/ws/secured/internal/live"
CLIENT_BASIC_AUTH = (
    "Basic dGVzdC1vYXV0aC1jbGllbnQtaWQ6JDJ5JDEyJHZYT1V0RWVuVkZDTzFaZ3ky"
    "WWllUHVGM1dGL3NEZ05PM1luaFJqbDQ5TklEbEViR2VTZU91"
)
USER_AGENT = "notiOne/2.2.3 (Android; Home Assistant API probe)"


def ssl_context() -> ssl.SSLContext:
    """Build a verified context, including portable Python installations."""
    default_cafile = ssl.get_default_verify_paths().cafile
    if default_cafile and os.path.exists(default_cafile):
        return ssl.create_default_context()
    for cafile in ("/etc/ssl/cert.pem", "/opt/homebrew/etc/openssl@3/cert.pem"):
        if os.path.exists(cafile):
            return ssl.create_default_context(cafile=cafile)
    return ssl.create_default_context()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email")
    parser.add_argument("--device-id", type=int)
    parser.add_argument("--imei", type=int)
    parser.add_argument("--duration", type=int, default=120)
    parser.add_argument(
        "--start-live",
        action="store_true",
        help="required confirmation that the script may activate LIVE mode",
    )
    args = parser.parse_args()
    if args.duration < 1:
        parser.error("--duration must be positive")
    if not args.start_live:
        parser.error("LIVE activation requires the explicit --start-live flag")
    return args


def request_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    payload: dict | None = None,
) -> dict:
    body = None
    request_headers = {"User-Agent": USER_AGENT, **(headers or {})}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        url, data=body, headers=request_headers, method=method
    )
    try:
        with urllib.request.urlopen(
            request, timeout=20, context=ssl_context()
        ) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {error.code} from {url}: {detail}") from error


def login(email: str, password: str) -> tuple[str, str]:
    data = request_json(
        LOGIN_URL,
        method="POST",
        headers={"Authorization": CLIENT_BASIC_AUTH},
        payload={"email": email, "password": password, "scope": "NOTI"},
    )
    access_token = data.get("accessToken")
    token_type = data.get("tokenType", "Bearer")
    if not access_token:
        raise RuntimeError("login response is missing accessToken")
    return token_type, access_token


def select_device(token: str, device_id: int | None) -> tuple[int, int, str]:
    data = request_json(
        DEVICELIST_URL,
        headers={"Authorization": token, "Accept": "application/notinote.me-5+json"},
    )
    devices = data.get("deviceList") or []
    if device_id is not None:
        devices = [device for device in devices if device.get("deviceId") == device_id]
    else:
        devices = [
            device
            for device in devices
            if device.get("gpsDetails", {}).get("imei")
        ]
    if not devices:
        raise RuntimeError("no matching GPS device with an IMEI was found")
    device = devices[0]
    imei = device.get("gpsDetails", {}).get("imei")
    if not isinstance(imei, int):
        raise RuntimeError("selected device has no numeric gpsDetails.imei")
    return device["deviceId"], imei, device.get("name") or "unnamed"


def encode_varint(value: int) -> bytes:
    output = bytearray()
    while value > 0x7F:
        output.append((value & 0x7F) | 0x80)
        value >>= 7
    output.append(value)
    return bytes(output)


def read_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while offset < len(data):
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, offset
        shift += 7
        if shift > 63:
            break
    raise ValueError("invalid protobuf varint")


def parse_protobuf(data: bytes) -> dict[int, list[tuple[int, object]]]:
    fields: dict[int, list[tuple[int, object]]] = {}
    offset = 0
    while offset < len(data):
        key, offset = read_varint(data, offset)
        field_number = key >> 3
        wire_type = key & 7
        if wire_type == 0:
            value, offset = read_varint(data, offset)
        elif wire_type == 1:
            value = data[offset : offset + 8]
            offset += 8
        elif wire_type == 2:
            length, offset = read_varint(data, offset)
            value = data[offset : offset + length]
            offset += length
        elif wire_type == 5:
            value = data[offset : offset + 4]
            offset += 4
        else:
            raise ValueError(f"unsupported protobuf wire type {wire_type}")
        fields.setdefault(field_number, []).append((wire_type, value))
    return fields


def first_field(fields: dict, number: int, default=None):
    values = fields.get(number)
    return values[0][1] if values else default


def build_enable_request(imei: int) -> bytes:
    inner = b"\x08" + encode_varint(imei)
    # WSMessage.type is LIVE_MODE_ENABLE_REQUEST=0, so proto3 omits it.
    return b"\x12" + encode_varint(len(inner)) + inner


def parse_server_message(payload: bytes) -> tuple[str, dict]:
    outer = parse_protobuf(payload)
    message_type = first_field(outer, 1, 0)
    body = first_field(outer, 2, b"")
    if not isinstance(body, bytes):
        raise ValueError("WebSocket protobuf message has no body")
    fields = parse_protobuf(body)
    if message_type == 1:
        gps_time = first_field(fields, 2, 0)
        return "sample", {
            "imei": first_field(fields, 1, 0),
            "gpsTime": gps_time,
            "gpsTimeUtc": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(gps_time / 1000)
            ),
            "longitude": struct.unpack("<d", first_field(fields, 3))[0],
            "latitude": struct.unpack("<d", first_field(fields, 4))[0],
            "speed": first_field(fields, 5, 0),
            "altitude": first_field(fields, 6, 0),
            "azimuth": first_field(fields, 7, 0),
        }
    if message_type == 2:
        return "config", {
            "imei": first_field(fields, 1, 0),
            "maxSessionTime": first_field(fields, 2, 0),
        }
    return "unknown", {"type": message_type, "payloadHex": body.hex()}


def recv_exact(sock: ssl.SSLSocket, length: int) -> bytes:
    output = bytearray()
    while len(output) < length:
        chunk = sock.recv(length - len(output))
        if not chunk:
            raise ConnectionError("WebSocket connection closed unexpectedly")
        output.extend(chunk)
    return bytes(output)


def send_frame(sock: ssl.SSLSocket, opcode: int, payload: bytes = b"") -> None:
    mask = os.urandom(4)
    length = len(payload)
    header = bytearray([0x80 | opcode])
    if length < 126:
        header.append(0x80 | length)
    elif length < 65536:
        header.append(0x80 | 126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(0x80 | 127)
        header.extend(struct.pack("!Q", length))
    header.extend(mask)
    masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    sock.sendall(header + masked)


def read_frame(sock: ssl.SSLSocket) -> tuple[int, bytes]:
    first, second = recv_exact(sock, 2)
    opcode = first & 0x0F
    length = second & 0x7F
    masked = bool(second & 0x80)
    if length == 126:
        length = struct.unpack("!H", recv_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", recv_exact(sock, 8))[0]
    mask = recv_exact(sock, 4) if masked else b""
    payload = recv_exact(sock, length)
    if masked:
        payload = bytes(
            byte ^ mask[index % 4] for index, byte in enumerate(payload)
        )
    return opcode, payload


def connect_websocket(authorization: str) -> ssl.SSLSocket:
    raw_socket = socket.create_connection((WS_HOST, WS_PORT), timeout=20)
    sock = ssl_context().wrap_socket(raw_socket, server_hostname=WS_HOST)
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (
        f"GET {WS_PATH} HTTP/1.1\r\n"
        f"Host: {WS_HOST}:{WS_PORT}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        f"Authorization: {authorization}\r\n"
        f"User-Agent: {USER_AGENT}\r\n\r\n"
    )
    sock.sendall(request.encode("ascii"))
    response = bytearray()
    while b"\r\n\r\n" not in response:
        response.extend(sock.recv(4096))
        if len(response) > 65536:
            raise RuntimeError("oversized WebSocket handshake response")
    headers = response.decode("iso-8859-1").split("\r\n")
    if " 101 " not in headers[0]:
        raise RuntimeError(f"WebSocket handshake failed: {headers[0]}")
    expected_accept = base64.b64encode(
        hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
    ).decode("ascii")
    response_headers = {
        name.lower(): value.strip()
        for line in headers[1:]
        if ":" in line
        for name, value in [line.split(":", 1)]
    }
    if response_headers.get("sec-websocket-accept") != expected_accept:
        raise RuntimeError("invalid Sec-WebSocket-Accept response")
    return sock


def run() -> int:
    args = parse_args()
    password = getpass.getpass("notiOne password: ")
    token_type, access_token = login(args.email, password)
    authorization = f"{token_type.strip().capitalize()} {access_token}"

    if args.imei is None:
        device_id, imei, name = select_device(authorization, args.device_id)
    else:
        device_id, imei, name = args.device_id or 0, args.imei, "manual IMEI"

    print(f"Device: {name} (deviceId={device_id}, imei={imei})")
    print(f"Connecting to wss://{WS_HOST}:{WS_PORT}{WS_PATH}")
    sock = connect_websocket(authorization)
    sock.settimeout(15)
    send_frame(sock, 0x2, build_enable_request(imei))
    print(f"LIVE request sent; observing for up to {args.duration}s")

    deadline = time.monotonic() + args.duration
    sample_count = 0
    previous_gps_time: int | None = None
    close_sent = False
    try:
        while time.monotonic() < deadline:
            try:
                opcode, payload = read_frame(sock)
            except socket.timeout:
                print("No WebSocket message for 15 seconds", file=sys.stderr)
                continue
            if opcode == 0x2:
                kind, data = parse_server_message(payload)
                if kind == "sample":
                    sample_count += 1
                    gps_time = data["gpsTime"]
                    data["deltaSeconds"] = (
                        None
                        if previous_gps_time is None
                        else (gps_time - previous_gps_time) / 1000
                    )
                    previous_gps_time = gps_time
                print(json.dumps({"event": kind, **data}, ensure_ascii=False))
            elif opcode == 0x8:
                code = struct.unpack("!H", payload[:2])[0] if len(payload) >= 2 else None
                reason = payload[2:].decode("utf-8", errors="replace")
                print(json.dumps({"event": "close", "code": code, "reason": reason}))
                break
            elif opcode == 0x9:
                send_frame(sock, 0xA, payload)
            elif opcode == 0xA:
                continue
    finally:
        try:
            send_frame(sock, 0x8, struct.pack("!H", 3000) + b"API probe finished")
            close_sent = True
        except OSError:
            pass
        sock.close()

    print(f"Finished; received {sample_count} LIVE samples; close_sent={close_sent}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except (ConnectionError, OSError, RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
