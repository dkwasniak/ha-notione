"""Tests for the dependency-free notiOne LIVE protobuf codec."""

from __future__ import annotations

import struct
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "notione"
    / "live_protocol.py"
)
_SPEC = spec_from_file_location("notione_live_protocol", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_PROTOCOL = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_PROTOCOL)
build_enable_request = _PROTOCOL.build_enable_request
encode_varint = _PROTOCOL.encode_varint
parse_server_message = _PROTOCOL.parse_server_message
read_varint = _PROTOCOL.read_varint
reason_for_close_code = _PROTOCOL.reason_for_close_code


def _field(number: int, wire_type: int, value: bytes) -> bytes:
    return encode_varint((number << 3) | wire_type) + value


def _bytes_field(number: int, value: bytes) -> bytes:
    return _field(number, 2, encode_varint(len(value)) + value)


class LiveProtocolTest(unittest.TestCase):
    def test_varint_round_trip(self) -> None:
        for value in (0, 1, 127, 128, 300, 8_600_000_000_000_001):
            encoded = encode_varint(value)
            self.assertEqual((value, len(encoded)), read_varint(encoded))

    def test_enable_request_omits_zero_type(self) -> None:
        imei = 123456789012345
        body = b"\x08" + encode_varint(imei)
        self.assertEqual(_bytes_field(2, body), build_enable_request(imei))

    def test_parse_config(self) -> None:
        body = _field(1, 0, encode_varint(123)) + _field(
            2, 0, encode_varint(1800)
        )
        payload = _field(1, 0, encode_varint(2)) + _bytes_field(2, body)
        self.assertEqual(
            ("config", {"imei": 123, "max_session_time": 1800}),
            parse_server_message(payload),
        )

    def test_parse_sample(self) -> None:
        body = b"".join(
            (
                _field(1, 0, encode_varint(123)),
                _field(2, 0, encode_varint(1_700_000_000_000)),
                _field(3, 1, struct.pack("<d", 17.03)),
                _field(4, 1, struct.pack("<d", 51.10)),
                _field(5, 0, encode_varint(42)),
                _field(6, 0, encode_varint(120)),
                _field(7, 0, encode_varint(270)),
            )
        )
        payload = _field(1, 0, encode_varint(1)) + _bytes_field(2, body)
        kind, sample = parse_server_message(payload)
        self.assertEqual("sample", kind)
        self.assertEqual(1_700_000_000_000, sample["gpstime"])
        self.assertAlmostEqual(17.03, sample["longitude"])
        self.assertAlmostEqual(51.10, sample["latitude"])
        self.assertEqual(42, sample["speed"])

    def test_rejects_truncated_fixed64(self) -> None:
        body = _field(3, 1, b"\0" * 7)
        payload = _field(1, 0, encode_varint(1)) + _bytes_field(2, body)
        with self.assertRaises(ValueError):
            parse_server_message(payload)

    def test_maps_all_known_close_codes(self) -> None:
        self.assertEqual("client_stop", reason_for_close_code(3000))
        self.assertEqual("server_error", reason_for_close_code(4000))
        self.assertEqual("already_registered", reason_for_close_code(4001))
        self.assertEqual("idle_timeout", reason_for_close_code(4002))
        self.assertEqual("session_limit", reason_for_close_code(4003))
        self.assertEqual("device_not_registered", reason_for_close_code(4004))
        self.assertEqual("device_response_timeout", reason_for_close_code(4005))
        self.assertIsNone(reason_for_close_code(4999))


if __name__ == "__main__":
    unittest.main()
