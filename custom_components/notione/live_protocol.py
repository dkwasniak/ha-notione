"""Minimal protobuf codec for the notiOne LIVE WebSocket protocol."""

from __future__ import annotations

import struct
from typing import Any

_CLOSE_REASONS = {
    3000: "client_stop",
    4000: "server_error",
    4001: "already_registered",
    4002: "idle_timeout",
    4003: "session_limit",
    4004: "device_not_registered",
    4005: "device_response_timeout",
}


def reason_for_close_code(code: int | None) -> str | None:
    """Map known notiOne WebSocket close codes to stable reasons."""
    return _CLOSE_REASONS.get(code)


def encode_varint(value: int) -> bytes:
    """Encode an unsigned protobuf varint."""
    if value < 0:
        raise ValueError("varint cannot be negative")
    output = bytearray()
    while value > 0x7F:
        output.append((value & 0x7F) | 0x80)
        value >>= 7
    output.append(value)
    return bytes(output)


def read_varint(data: bytes, offset: int = 0) -> tuple[int, int]:
    """Decode an unsigned protobuf varint and return its new offset."""
    value = 0
    shift = 0
    while offset < len(data) and shift <= 63:
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, offset
        shift += 7
    raise ValueError("invalid protobuf varint")


def _parse_fields(data: bytes) -> dict[int, list[tuple[int, Any]]]:
    fields: dict[int, list[tuple[int, Any]]] = {}
    offset = 0
    while offset < len(data):
        key, offset = read_varint(data, offset)
        number, wire_type = key >> 3, key & 7
        if number == 0:
            raise ValueError("invalid protobuf field number")
        if wire_type == 0:
            value, offset = read_varint(data, offset)
        elif wire_type == 1:
            if offset + 8 > len(data):
                raise ValueError("truncated fixed64 field")
            value = data[offset : offset + 8]
            offset += 8
        elif wire_type == 2:
            length, offset = read_varint(data, offset)
            if offset + length > len(data):
                raise ValueError("truncated bytes field")
            value = data[offset : offset + length]
            offset += length
        elif wire_type == 5:
            if offset + 4 > len(data):
                raise ValueError("truncated fixed32 field")
            value = data[offset : offset + 4]
            offset += 4
        else:
            raise ValueError(f"unsupported protobuf wire type {wire_type}")
        fields.setdefault(number, []).append((wire_type, value))
    return fields


def _first(fields: dict[int, list[tuple[int, Any]]], number: int, default: Any) -> Any:
    values = fields.get(number)
    return values[0][1] if values else default


def build_enable_request(imei: int) -> bytes:
    """Build WSMessage(LIVE_MODE_ENABLE_REQUEST, LiveGpsEnableRequest)."""
    body = b"\x08" + encode_varint(imei)
    return b"\x12" + encode_varint(len(body)) + body


def parse_server_message(payload: bytes) -> tuple[str, dict[str, Any]]:
    """Parse a LIVE config or sample envelope."""
    envelope = _parse_fields(payload)
    message_type = _first(envelope, 1, 0)
    body = _first(envelope, 2, b"")
    if not isinstance(body, bytes):
        raise ValueError("LIVE message has no body")
    fields = _parse_fields(body)
    if message_type == 1:
        longitude = _first(fields, 3, None)
        latitude = _first(fields, 4, None)
        if not isinstance(longitude, bytes) or not isinstance(latitude, bytes):
            raise ValueError("LIVE sample is missing coordinates")
        return "sample", {
            "imei": _first(fields, 1, 0),
            "gpstime": _first(fields, 2, 0),
            "longitude": struct.unpack("<d", longitude)[0],
            "latitude": struct.unpack("<d", latitude)[0],
            "speed": _first(fields, 5, 0),
            "altitude": _first(fields, 6, 0),
            "azimuth": _first(fields, 7, 0),
        }
    if message_type == 2:
        return "config", {
            "imei": _first(fields, 1, 0),
            "max_session_time": _first(fields, 2, 0),
        }
    return "unknown", {"type": message_type}
