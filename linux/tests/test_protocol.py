"""Unit tests for VCamdroid binary protocol serialization/deserialization."""

import struct
import unittest

from vcamdroid.protocol import (
    DeviceDescriptor,
    ErrorReport,
    ErrorSeverity,
    FilterCategory,
    PacketType,
    StreamOptions,
    TruncatedErrorReportError,
    build_bitrate_packet,
    build_correction_filter_packet,
    build_effect_filter_packet,
    build_resolution_packet,
    build_rotate_packet,
    build_zoom_packet,
)
from vcamdroid_linux import parse_resolution


def _pack_be_str(s: str) -> bytes:
    raw = s.encode("utf-8")
    return struct.pack(">H", len(raw)) + raw


class ProtocolTests(unittest.TestCase):
    def test_device_descriptor_roundtrip(self) -> None:
        payload = bytearray()
        payload.extend(_pack_be_str("Pixel 8"))
        payload.extend(_pack_be_str("rtsp://127.0.0.1:8554/"))
        payload.extend(struct.pack(">H", 1))
        payload.extend(struct.pack(">HH", 640, 480))
        payload.extend(struct.pack(">H", 2))
        payload.extend(struct.pack(">HH", 1280, 720))
        payload.extend(struct.pack(">HH", 1920, 1080))
        payload.extend(struct.pack(">H", 2))
        payload.extend(_pack_be_str("Brightness"))
        payload.append(FilterCategory.CORRECTION)
        payload.extend(_pack_be_str("Sepia"))
        payload.append(FilterCategory.EFFECT)

        desc = DeviceDescriptor.deserialize(bytes(payload))
        self.assertEqual(desc.name, "Pixel 8")
        self.assertEqual(desc.rtsp_url, "rtsp://127.0.0.1:8554/")
        self.assertEqual(desc.protocol, "tcp")
        self.assertEqual(desc.front_resolutions, [(640, 480)])
        self.assertEqual(desc.back_resolutions, [(1280, 720), (1920, 1080)])
        self.assertEqual(desc.filters[FilterCategory.CORRECTION], ["Brightness"])
        self.assertEqual(desc.filters[FilterCategory.EFFECT], ["Sepia"])

    def test_error_report_deserialize(self) -> None:
        payload = bytes([ErrorSeverity.WARNING]) + _pack_be_str("Encoder") + _pack_be_str("Fallback")
        report = ErrorReport.deserialize(payload)
        self.assertEqual(report.severity, ErrorSeverity.WARNING)
        self.assertEqual(report.error, "Encoder")
        self.assertEqual(report.description, "Fallback")

    def test_stream_options_activation_layout(self) -> None:
        opts = StreamOptions(
            fps=30,
            resolution=(1280, 720),
            back_camera_active=True,
            adaptive_bitrate=False,
            bitrate=4000,
            min_bitrate=2000,
            max_bitrate=12000,
            stabilization_enabled=True,
            flash_enabled=False,
            h265_enabled=True,
            focus_mode=2,
            filter_slider_values={"Brightness": 55},
            active_effect_filter="Sepia",
        )
        raw = opts.serialize_activation()
        self.assertEqual(raw[0], PacketType.ACTIVATION)
        # Verify fixed header offsets match Android StreamOptions.deserialize()
        fps, w, h, cam = struct.unpack_from(">iiii", raw, 1)
        self.assertEqual((fps, w, h, cam), (30, 1280, 720, 1))
        self.assertEqual(raw[17], 0)  # adaptive_bitrate (1 byte)
        br, min_br, max_br = struct.unpack_from(">iii", raw, 18)
        self.assertEqual((br, min_br, max_br), (4000 * 1024, 2000 * 1024, 12000 * 1024))
        self.assertEqual((raw[30], raw[31], raw[32]), (1, 0, 1))  # stab, flash, h265
        focus = struct.unpack_from(">i", raw, 33)[0]
        self.assertEqual(focus, 2)

    def test_control_packets(self) -> None:
        self.assertEqual(build_resolution_packet(1280, 720), struct.pack("<BHH", PacketType.RESOLUTION, 1280, 720))
        self.assertEqual(build_bitrate_packet(4000), struct.pack("<BH", PacketType.BITRATE, 4000))
        self.assertEqual(build_zoom_packet(2.5), struct.pack("<Bf", PacketType.ZOOM, 2.5))
        self.assertEqual(build_correction_filter_packet("Gamma", 60), b"\x05\x05Gamma\x3c")
        self.assertEqual(build_effect_filter_packet("Sepia"), b"\x06\x05Sepia")

    def test_multiple_error_reports_in_one_buffer(self) -> None:
        payload = b"".join(
            bytes([ErrorSeverity.WARNING]) + _pack_be_str("Encoder") + _pack_be_str("Fallback")
            for _ in range(3)
        )
        offset = 0
        errors = []
        while offset < len(payload):
            report, offset = ErrorReport.deserialize_with_offset(payload, offset)
            errors.append(report.error)
        self.assertEqual(errors, ["Encoder", "Encoder", "Encoder"])
        self.assertEqual(offset, len(payload))

    def test_partial_error_report_is_truncated(self) -> None:
        payload = bytes([ErrorSeverity.ERROR]) + _pack_be_str("Encoder") + _pack_be_str("Fallback")
        with self.assertRaises(TruncatedErrorReportError):
            ErrorReport.deserialize_with_offset(payload[: len(payload) - 1])

    def test_descriptor_consumed_offset_ignores_trailing_bytes(self) -> None:
        payload = bytearray()
        payload.extend(_pack_be_str("Pixel 8"))
        payload.extend(_pack_be_str("rtsp://127.0.0.1:8554/"))
        payload.extend(struct.pack(">HHH", 0, 0, 0))
        trailing = bytes([ErrorSeverity.WARNING]) + _pack_be_str("Encoder") + _pack_be_str("Fallback")
        payload.extend(trailing)

        desc, consumed = DeviceDescriptor.deserialize_with_offset(bytes(payload))
        self.assertEqual(desc.name, "Pixel 8")
        self.assertEqual(consumed, len(payload) - len(trailing))

    def test_unknown_filter_category_is_preserved(self) -> None:
        payload = bytearray()
        payload.extend(_pack_be_str("Pixel 8"))
        payload.extend(_pack_be_str("rtsp://127.0.0.1:8554/"))
        payload.extend(struct.pack(">HHH", 0, 0, 1))
        payload.extend(_pack_be_str("Future effect"))
        payload.append(99)
        desc = DeviceDescriptor.deserialize(bytes(payload))
        self.assertEqual(desc.filters[99], ["Future effect"])

    def test_packet_value_validation(self) -> None:
        with self.assertRaises(ValueError):
            build_rotate_packet(360)
        with self.assertRaises(ValueError):
            build_bitrate_packet(70000)
        with self.assertRaises(ValueError):
            StreamOptions(filter_slider_values={"x": 2**40}).serialize_activation()

    def test_parse_resolution(self) -> None:
        self.assertEqual(parse_resolution("1280x720"), (1280, 720))
        with self.assertRaises(Exception):
            parse_resolution("1280*720")
        with self.assertRaises(Exception):
            parse_resolution("0x720")


if __name__ == "__main__":
    unittest.main()
