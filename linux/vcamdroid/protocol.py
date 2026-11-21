"""Binary protocol definitions, serialization, and deserialization for VCamdroid."""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from enum import IntEnum
from urllib.parse import urlsplit


class PacketType(IntEnum):
    FRAME = 0x00
    RESOLUTION = 0x01
    ACTIVATION = 0x02
    CAMERA = 0x03
    QUALITY = 0x04
    CORRECTION_FILTER = 0x05
    EFFECT_FILTER = 0x06
    ROTATION = 0x07
    BITRATE = 0x08
    ADAPTIVE_BITRATE = 0x09
    STABILIZATION = 0x0A
    FLASH = 0x0B
    FOCUS = 0x0C
    CODEC = 0x0D
    FPS = 0x0E
    ZOOM = 0x0F
    FLIP = 0x10


class FilterCategory(IntEnum):
    NONE = 0
    CORRECTION = 1
    EFFECT = 2
    DISTORTION = 3
    ARTISTIC = 4


class ErrorSeverity(IntEnum):
    WARNING = 0
    ERROR = 1


class TruncatedDescriptorError(ValueError):
    """Raised when more TCP bytes are needed to finish parsing DeviceDescriptor."""


class TruncatedErrorReportError(ValueError):
    """Raised when more TCP bytes are needed to finish parsing ErrorReport."""


def _check_range(value: int, low: int, high: int, name: str) -> int:
    """Validate an integer before packing it into a fixed-width wire field."""
    if not low <= value <= high:
        raise ValueError(f"{name} out of range [{low}, {high}]: {value}")
    return value


def _check_u8(value: int, name: str) -> int:
    return _check_range(value, 0, 0xFF, name)


def _check_u16(value: int, name: str) -> int:
    return _check_range(value, 0, 0xFFFF, name)


def _check_i32(value: int, name: str) -> int:
    return _check_range(value, -(2**31), 2**31 - 1, name)


@dataclass
class DeviceDescriptor:
    name: str
    rtsp_url: str
    protocol: str
    front_resolutions: list[tuple[int, int]] = field(default_factory=list)
    back_resolutions: list[tuple[int, int]] = field(default_factory=list)
    # Keys are FilterCategory values where known; unknown raw category codes are
    # preserved as ints so newer APKs do not silently lose their filters.
    filters: dict[int, list[str]] = field(default_factory=dict)

    @classmethod
    def deserialize(cls, data: bytes) -> DeviceDescriptor:
        """Deserialize a Big-Endian DeviceDescriptor packet sent by Android."""
        descriptor, _ = cls.deserialize_with_offset(data)
        return descriptor

    @classmethod
    def deserialize_with_offset(cls, data: bytes) -> tuple[DeviceDescriptor, int]:
        """Deserialize a DeviceDescriptor and return (descriptor, end offset)."""
        offset = 0

        def read_uint16() -> int:
            nonlocal offset
            if offset + 2 > len(data):
                raise TruncatedDescriptorError("Truncated uint16 in DeviceDescriptor")
            val = struct.unpack_from(">H", data, offset)[0]
            offset += 2
            return val

        def read_string(max_len: int = 4096) -> str:
            nonlocal offset
            length = read_uint16()
            if length > max_len:
                raise ValueError(
                    f"Unexpected string length ({length}); client may be using an older VCamdroid APK"
                )
            if offset + length > len(data):
                raise TruncatedDescriptorError("Truncated string in DeviceDescriptor")
            val = data[offset : offset + length].decode("utf-8", errors="replace")
            offset += length
            return val

        name = read_string(max_len=256)
        url = read_string()
        try:
            host = urlsplit(url).hostname or ""
        except ValueError:
            host = ""
        # Android uses adb reverse (device connects to 127.0.0.1) for USB mode
        # and a direct LAN address for Wi-Fi mode.
        protocol = "tcp" if host in {"127.0.0.1", "localhost", "::1"} else "udp"

        front_count = read_uint16()
        front_resolutions: list[tuple[int, int]] = []
        for _ in range(front_count):
            front_resolutions.append((read_uint16(), read_uint16()))

        back_count = read_uint16()
        back_resolutions: list[tuple[int, int]] = []
        for _ in range(back_count):
            back_resolutions.append((read_uint16(), read_uint16()))

        filter_count = read_uint16()
        filters: dict[int, list[str]] = {}
        for _ in range(filter_count):
            fname = read_string(max_len=256)
            if offset >= len(data):
                raise TruncatedDescriptorError("Truncated filter category in DeviceDescriptor")
            cat_raw = data[offset]
            offset += 1
            filters.setdefault(cat_raw, []).append(fname)

        return cls(
            name=name,
            rtsp_url=url,
            protocol=protocol,
            front_resolutions=front_resolutions,
            back_resolutions=back_resolutions,
            filters=filters,
        ), offset


@dataclass
class ErrorReport:
    severity: ErrorSeverity
    error: str
    description: str

    @classmethod
    def deserialize(cls, data: bytes) -> ErrorReport:
        """Deserialize the first Big-Endian ErrorReport in ``data``."""
        report, _ = cls.deserialize_with_offset(data)
        return report

    @classmethod
    def deserialize_with_offset(cls, data: bytes, offset: int = 0) -> tuple[ErrorReport, int]:
        """Deserialize one ErrorReport at ``offset`` and return (report, end offset).

        TCP is a byte stream, so a single recv() can contain several reports or
        only part of one. Callers keep a buffer and retry until this raises
        TruncatedErrorReportError, then wait for more bytes.
        """
        if offset + 1 > len(data):
            raise TruncatedErrorReportError("Truncated severity in ErrorReport")
        sev_raw = data[offset]
        offset += 1
        try:
            severity = ErrorSeverity(sev_raw)
        except ValueError:
            severity = ErrorSeverity.ERROR

        def read_string() -> str:
            nonlocal offset
            if offset + 2 > len(data):
                raise TruncatedErrorReportError("Truncated string length in ErrorReport")
            length = struct.unpack_from(">H", data, offset)[0]
            offset += 2
            if offset + length > len(data):
                raise TruncatedErrorReportError("Truncated string in ErrorReport")
            val = data[offset : offset + length].decode("utf-8", errors="replace")
            offset += length
            return val

        error = read_string()
        description = read_string()
        return cls(severity=severity, error=error, description=description), offset


@dataclass
class StreamOptions:
    fps: int = 30
    resolution: tuple[int, int] = (1920, 1080)
    back_camera_active: bool = True
    adaptive_bitrate: bool = False
    bitrate: int = 8000
    min_bitrate: int = 2000
    max_bitrate: int = 12000
    stabilization_enabled: bool = False
    flash_enabled: bool = False
    h265_enabled: bool = False
    focus_mode: int = 0
    filter_slider_values: dict[str, int] = field(default_factory=dict)
    active_effect_filter: str = ""
    zoom: float = 1.0

    def serialize_activation(self) -> bytes:
        """Serialize ACTIVATION packet matching Android StreamOptions.deserialize()."""
        fps = _check_i32(self.fps, "fps")
        width = _check_i32(self.resolution[0], "resolution width")
        height = _check_i32(self.resolution[1], "resolution height")
        focus_mode = _check_i32(self.focus_mode, "focus_mode")
        bitrate = _check_i32(self.bitrate * 1024, "bitrate")
        min_bitrate = _check_i32(self.min_bitrate * 1024, "min_bitrate")
        max_bitrate = _check_i32(self.max_bitrate * 1024, "max_bitrate")

        encoded_filters: list[tuple[bytes, int]] = []
        for name, val in self.filter_slider_values.items():
            encoded = name.encode("utf-8")
            _check_u16(len(encoded), f"filter name '{name}' length")
            encoded_filters.append((encoded, _check_i32(val, f"filter '{name}' value")))
        _check_u16(len(encoded_filters), "filter count")

        effect_bytes = self.active_effect_filter.encode("utf-8")
        _check_u16(len(effect_bytes), "active effect filter length")

        buf = bytearray()
        buf.append(PacketType.ACTIVATION)

        # Fixed fields (Big-Endian) matching StreamOptions.kt
        buf.extend(struct.pack(">iii", fps, width, height))
        buf.extend(struct.pack(">i", 1 if self.back_camera_active else 0))
        buf.append(1 if self.adaptive_bitrate else 0)
        buf.extend(struct.pack(">iii", bitrate, min_bitrate, max_bitrate))
        buf.append(1 if self.stabilization_enabled else 0)
        buf.append(1 if self.flash_enabled else 0)
        buf.append(1 if self.h265_enabled else 0)
        buf.extend(struct.pack(">i", focus_mode))

        # Correction filter slider values
        buf.extend(struct.pack(">H", len(encoded_filters)))
        for encoded, val in encoded_filters:
            buf.extend(struct.pack(">H", len(encoded)))
            buf.extend(encoded)
            buf.extend(struct.pack(">i", val))

        # Active effect filter
        buf.extend(struct.pack(">H", len(effect_bytes)))
        buf.extend(effect_bytes)

        return bytes(buf)


# The control packets below are intentionally little-endian: StreamActivity.kt
# decodes width/height/bitrate/zoom by shifting buffer bytes left. Only the
# ACTIVATION payload is Big-Endian (java.nio.ByteBuffer default).


def build_resolution_packet(width: int, height: int) -> bytes:
    return struct.pack(
        "<BHH", PacketType.RESOLUTION, _check_u16(width, "width"), _check_u16(height, "height")
    )


def build_fps_packet(fps: int) -> bytes:
    return struct.pack("<BB", PacketType.FPS, _check_u8(fps, "fps"))


def build_bitrate_packet(bitrate: int) -> bytes:
    return struct.pack("<BH", PacketType.BITRATE, _check_u16(bitrate, "bitrate"))


def build_adaptive_bitrate_packet(min_bitrate: int, max_bitrate: int) -> bytes:
    return struct.pack(
        "<BHH",
        PacketType.ADAPTIVE_BITRATE,
        _check_u16(min_bitrate, "min_bitrate"),
        _check_u16(max_bitrate, "max_bitrate"),
    )


def build_stabilization_packet(enabled: bool) -> bytes:
    return struct.pack("<BB", PacketType.STABILIZATION, 1 if enabled else 0)


def build_flash_packet(enabled: bool) -> bytes:
    return struct.pack("<BB", PacketType.FLASH, 1 if enabled else 0)


def build_focus_packet(mode: int) -> bytes:
    return struct.pack("<BB", PacketType.FOCUS, _check_u8(mode, "focus mode"))


def build_codec_packet(h265_enabled: bool) -> bytes:
    return struct.pack("<BB", PacketType.CODEC, 1 if h265_enabled else 0)


def build_swap_camera_packet() -> bytes:
    return bytes([PacketType.CAMERA])


def build_rotate_packet(degrees: int) -> bytes:
    return struct.pack("<BB", PacketType.ROTATION, _check_u8(degrees, "rotation degrees"))


def build_zoom_packet(factor: float) -> bytes:
    if not math.isfinite(factor):
        raise ValueError(f"zoom factor must be finite: {factor}")
    return struct.pack("<Bf", PacketType.ZOOM, factor)


def build_flip_packet(horizontal: bool) -> bytes:
    return struct.pack("<BB", PacketType.FLIP, 1 if horizontal else 0)


def build_correction_filter_packet(name: str, value: int) -> bytes:
    encoded = name.encode("utf-8")
    return (
        bytes([PacketType.CORRECTION_FILTER, _check_u8(len(encoded), "filter name length")])
        + encoded
        + bytes([_check_u8(value, "filter value")])
    )


def build_effect_filter_packet(name: str) -> bytes:
    encoded = name.encode("utf-8")
    return bytes([PacketType.EFFECT_FILTER, _check_u8(len(encoded), "filter name length")]) + encoded
