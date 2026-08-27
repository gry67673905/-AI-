from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from app.application.dtos import (
    DocumentFrameData,
    VisionFrameData,
    VisionTicketClaimsData,
)


class VisionProtocolError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _reject_constant(_: str) -> None:
    raise VisionProtocolError("invalid_json")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise VisionProtocolError("invalid_json")
        value[key] = item
    return value


def _strict_object(raw: str, *, max_bytes: int) -> dict[str, Any]:
    try:
        encoded = raw.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise VisionProtocolError("invalid_utf8") from exc
    if not encoded or len(encoded) > max_bytes:
        raise VisionProtocolError("invalid_json_size")
    try:
        value = json.loads(
            raw,
            parse_constant=_reject_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise VisionProtocolError("invalid_json") from exc
    if not isinstance(value, dict):
        raise VisionProtocolError("invalid_json_shape")
    return value


def _exact_fields(value: dict[str, Any], names: set[str]) -> None:
    if set(value) != names:
        raise VisionProtocolError("invalid_fields")


def _integer(
    value: Any, code: str, *, minimum: int = 0, maximum: int = 2**63 - 1
) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise VisionProtocolError(code)
    return value


def parse_control_message(raw: str) -> dict[str, Any]:
    value = _strict_object(raw, max_bytes=2048)
    if value.get("v") != 1 or not isinstance(value.get("type"), str):
        raise VisionProtocolError("unsupported_control")
    message_type = value["type"]
    if message_type == "vision.start":
        _exact_fields(
            value,
            {"v", "type", "vision_session_id", "client_session_id"},
        )
        try:
            return {
                **value,
                "vision_session_id": UUID(str(value["vision_session_id"])),
                "client_session_id": UUID(str(value["client_session_id"])),
            }
        except ValueError as exc:
            raise VisionProtocolError("invalid_session_id") from exc
    if message_type in {"turn.start", "turn.end"}:
        _exact_fields(value, {"v", "type", "turn_seq"})
        return {
            **value,
            "turn_seq": _integer(
                value["turn_seq"], "invalid_turn_seq", minimum=1
            ),
        }
    if message_type == "document.start":
        _exact_fields(value, {"v", "type", "document_seq"})
        return {
            **value,
            "document_seq": _integer(
                value["document_seq"], "invalid_document_seq", minimum=1
            ),
        }
    raise VisionProtocolError("unsupported_control")


def _jpeg_dimensions(jpeg: bytes) -> tuple[int, int]:
    if len(jpeg) < 12 or not jpeg.startswith(b"\xff\xd8") or not jpeg.endswith(b"\xff\xd9"):
        raise VisionProtocolError("invalid_jpeg")
    position = 2
    sof_markers = {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
    while position + 3 < len(jpeg):
        if jpeg[position] != 0xFF:
            raise VisionProtocolError("invalid_jpeg")
        while position < len(jpeg) and jpeg[position] == 0xFF:
            position += 1
        if position >= len(jpeg):
            break
        marker = jpeg[position]
        position += 1
        if marker == 0xD9:
            break
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:
            continue
        if position + 2 > len(jpeg):
            break
        segment_length = int.from_bytes(jpeg[position : position + 2], "big")
        if segment_length < 2 or position + segment_length > len(jpeg):
            raise VisionProtocolError("invalid_jpeg")
        if marker in sof_markers:
            if segment_length < 7:
                raise VisionProtocolError("invalid_jpeg")
            height = int.from_bytes(jpeg[position + 3 : position + 5], "big")
            width = int.from_bytes(jpeg[position + 5 : position + 7], "big")
            if width <= 0 or height <= 0:
                raise VisionProtocolError("invalid_jpeg")
            return width, height
        if marker == 0xDA:
            break
        position += segment_length
    raise VisionProtocolError("jpeg_dimensions_missing")


def parse_frame_packet(
    packet: bytes,
    claims: VisionTicketClaimsData,
    *,
    max_frame_bytes: int,
    max_width: int,
    max_height: int,
    max_clock_skew_seconds: int,
    now_ms: int | None = None,
) -> VisionFrameData:
    if len(packet) < 5:
        raise VisionProtocolError("frame_too_short")
    header_length = int.from_bytes(packet[:4], "big", signed=False)
    if not 2 <= header_length <= 2048 or len(packet) <= 4 + header_length:
        raise VisionProtocolError("invalid_header_length")
    header_bytes = packet[4 : 4 + header_length]
    try:
        header_text = header_bytes.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise VisionProtocolError("invalid_utf8") from exc
    header = _strict_object(header_text, max_bytes=2048)
    _exact_fields(
        header,
        {
            "v",
            "type",
            "turn_seq",
            "frame_seq",
            "captured_at_ms",
            "width",
            "height",
            "camera",
        },
    )
    if header["v"] != 1 or header["type"] != "vision.frame":
        raise VisionProtocolError("unsupported_frame")
    turn_sequence = _integer(
        header["turn_seq"], "invalid_turn_seq", minimum=1
    )
    frame_sequence = _integer(
        header["frame_seq"], "invalid_frame_seq", minimum=1
    )
    captured_at_ms = _integer(
        header["captured_at_ms"], "invalid_capture_time", maximum=2**63 - 1
    )
    width = _integer(header["width"], "invalid_width", minimum=1, maximum=max_width)
    height = _integer(
        header["height"], "invalid_height", minimum=1, maximum=max_height
    )
    camera = header["camera"]
    if camera not in {"front", "back"}:
        raise VisionProtocolError("invalid_camera")
    current_ms = now_ms
    if current_ms is None:
        current_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    if abs(current_ms - captured_at_ms) > max_clock_skew_seconds * 1000:
        raise VisionProtocolError("stale_frame")

    jpeg = packet[4 + header_length :]
    if not jpeg or len(jpeg) > max_frame_bytes:
        raise VisionProtocolError("invalid_frame_size")
    jpeg_width, jpeg_height = _jpeg_dimensions(jpeg)
    if jpeg_width != width or jpeg_height != height:
        raise VisionProtocolError("dimension_mismatch")
    return VisionFrameData(
        vision_session_id=claims.vision_session_id,
        client_session_id=claims.client_session_id,
        turn_sequence=turn_sequence,
        frame_sequence=frame_sequence,
        captured_at_ms=captured_at_ms,
        received_at=datetime.now(timezone.utc),
        width=width,
        height=height,
        camera=camera,
        jpeg=jpeg,
    )


def binary_packet_type(packet: bytes) -> str:
    """Read only the bounded JSON envelope type before strict dispatch."""

    if len(packet) < 5:
        raise VisionProtocolError("frame_too_short")
    header_length = int.from_bytes(packet[:4], "big", signed=False)
    if not 2 <= header_length <= 2048 or len(packet) <= 4 + header_length:
        raise VisionProtocolError("invalid_header_length")
    try:
        raw = packet[4 : 4 + header_length].decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise VisionProtocolError("invalid_utf8") from exc
    header = _strict_object(raw, max_bytes=2048)
    message_type = header.get("type")
    if message_type not in {"vision.frame", "document.frame"}:
        raise VisionProtocolError("unsupported_frame")
    return message_type


def parse_document_frame_packet(
    packet: bytes,
    claims: VisionTicketClaimsData,
    *,
    max_frame_bytes: int = 1024 * 1024,
    max_dimension: int = 2048,
    max_clock_skew_seconds: int,
    now_ms: int | None = None,
) -> DocumentFrameData:
    """Strictly parse one high-resolution, user-triggered document photo.

    This is intentionally separate from ``parse_frame_packet`` so extending
    document capture cannot relax the ordinary streaming-frame contract.
    """

    if len(packet) < 5:
        raise VisionProtocolError("frame_too_short")
    header_length = int.from_bytes(packet[:4], "big", signed=False)
    if not 2 <= header_length <= 2048 or len(packet) <= 4 + header_length:
        raise VisionProtocolError("invalid_header_length")
    try:
        header_text = packet[4 : 4 + header_length].decode(
            "utf-8", errors="strict"
        )
    except UnicodeError as exc:
        raise VisionProtocolError("invalid_utf8") from exc
    header = _strict_object(header_text, max_bytes=2048)
    _exact_fields(
        header,
        {
            "v",
            "type",
            "document_seq",
            "captured_at_ms",
            "width",
            "height",
            "camera",
        },
    )
    if header["v"] != 1 or header["type"] != "document.frame":
        raise VisionProtocolError("unsupported_frame")
    document_sequence = _integer(
        header["document_seq"], "invalid_document_seq", minimum=1
    )
    captured_at_ms = _integer(
        header["captured_at_ms"], "invalid_capture_time", maximum=2**63 - 1
    )
    width = _integer(
        header["width"], "invalid_width", minimum=1, maximum=max_dimension
    )
    height = _integer(
        header["height"], "invalid_height", minimum=1, maximum=max_dimension
    )
    camera = header["camera"]
    if camera not in {"front", "back"}:
        raise VisionProtocolError("invalid_camera")
    current_ms = now_ms
    if current_ms is None:
        current_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    if abs(current_ms - captured_at_ms) > max_clock_skew_seconds * 1000:
        raise VisionProtocolError("stale_frame")
    jpeg = packet[4 + header_length :]
    if not jpeg or len(jpeg) > max_frame_bytes:
        raise VisionProtocolError("invalid_frame_size")
    jpeg_width, jpeg_height = _jpeg_dimensions(jpeg)
    if jpeg_width != width or jpeg_height != height:
        raise VisionProtocolError("dimension_mismatch")
    return DocumentFrameData(
        vision_session_id=claims.vision_session_id,
        client_session_id=claims.client_session_id,
        document_sequence=document_sequence,
        captured_at_ms=captured_at_ms,
        received_at=datetime.now(timezone.utc),
        width=width,
        height=height,
        camera=camera,
        jpeg=jpeg,
    )
