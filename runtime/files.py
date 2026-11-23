"""Files sent to Discord in multipart requests.

A file comes from the step either as a workflow file (``file_artifacts``: the host
grants the artifact through ``contracts/artifact_policies.yaml`` and the extension
reads it with ``read_artifact_bytes``) or as base64 text for small files (``files``).

The Content-Type of each part follows the file's extension and the types Discord
documents (developers/reference.mdx at discord-api-docs 9b737ec: "Image Formats" and
the "File Type Filtering" groups image, video and audio). An extension Discord does not
list is sent as ``application/octet-stream``. A sticker must be a PNG, APNG, GIF or
Lottie JSON file of at most 512 KiB (developers/resources/sticker.mdx, Create Guild
Sticker form params).
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

#: Extension -> Content-Type, from the documented image formats and file groups.
CONTENT_TYPES = {
    ".png": "image/png",
    ".apng": "image/apng",
    ".gif": "image/gif",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".jfif": "image/jpeg",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".json": "application/json",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".qt": "video/quicktime",
    ".webm": "video/webm",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".opus": "audio/opus",
    ".flac": "audio/flac",
}
DEFAULT_CONTENT_TYPE = "application/octet-stream"
#: Sticker files: PNG, APNG, GIF or Lottie JSON, at most 512 KiB.
STICKER_OPERATION = "create_guild_sticker"
STICKER_EXTENSIONS = frozenset({".png", ".apng", ".gif", ".json"})
MAX_STICKER_BYTES = 512 * 1024
MAX_FILES = 10


@dataclass(frozen=True)
class Part:
    name: str
    filename: str
    content_type: str
    data: bytes = field(repr=False)


def extension_of(filename: str) -> str:
    dot = filename.rfind(".")
    return filename[dot:].lower() if dot > 0 else ""


def content_type_for(filename: str) -> str:
    return CONTENT_TYPES.get(extension_of(filename), DEFAULT_CONTENT_TYPE)


ArtifactReader = Callable[[str], bytes]


def file_parts(
    operation_id: str,
    files: Any,
    artifacts: Any,
    *,
    read_artifact: ArtifactReader | None,
    valid_name: Callable[[str], bool],
) -> list[Part]:
    """Every file of the step, decoded or read, in the order given (base64 first)."""
    files = [] if files is None else files
    artifacts = [] if artifacts is None else artifacts
    if not isinstance(files, list) or not isinstance(artifacts, list):
        raise ValueError("Files must be lists")
    if len(files) + len(artifacts) > MAX_FILES:
        raise ValueError("At most ten files can be sent")
    parts: list[Part] = []
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != {"field", "filename", "data_base64"}:
            raise ValueError("Invalid multipart file")
        data = entry["data_base64"]
        if not isinstance(data, str):
            raise ValueError("Invalid multipart file")
        try:
            content = base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("A file is not valid base64") from None
        parts.append(_part(operation_id, entry["field"], entry["filename"], content, valid_name))
    for entry in artifacts:
        if not isinstance(entry, dict) or set(entry) != {"field", "filename", "artifact_handle"}:
            raise ValueError("Invalid workflow file")
        handle = entry["artifact_handle"]
        if not isinstance(handle, str) or not handle.strip() or read_artifact is None:
            raise ValueError("Invalid workflow file")
        _check_names(entry["field"], entry["filename"], valid_name)
        try:
            content = read_artifact(handle.strip())
        except Exception:  # noqa: BLE001 - any read failure: nothing was sent
            raise ValueError("The workflow file could not be read") from None
        parts.append(_part(operation_id, entry["field"], entry["filename"], content, valid_name))
    if len({part.name for part in parts}) != len(parts):
        raise ValueError("Duplicate multipart file field")
    return parts


def _check_names(name: Any, filename: Any, valid_name: Callable[[str], bool]) -> None:
    if (
        not isinstance(name, str)
        or not valid_name(name)
        or not isinstance(filename, str)
        or not valid_name(filename)
    ):
        raise ValueError("Invalid multipart field or filename")


def _part(
    operation_id: str, name: Any, filename: Any, content: bytes, valid_name: Callable[[str], bool]
) -> Part:
    _check_names(name, filename, valid_name)
    if operation_id == STICKER_OPERATION:
        if extension_of(filename) not in STICKER_EXTENSIONS:
            raise ValueError("A sticker must be a PNG, APNG, GIF or Lottie JSON file")
        if len(content) > MAX_STICKER_BYTES:
            raise ValueError("A sticker file is larger than 512 KiB")
    return Part(name, filename, content_type_for(filename), content)
