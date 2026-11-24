"""Files sent to Discord in multipart requests.

A file comes from the step either as a workflow file (``file_artifacts``: the host
grants the artifact through ``contracts/artifact_policies.yaml``) or as base64 text for
small files (``files``). A workflow file is streamed with the SDK's
``stream_artifact_bytes`` into a temporary file on disk, checked for its size as it
arrives; the SDK checks its SHA-256 when the stream ends. Nothing is sent before every
file was read and checked, because the multipart body's length is sent first. The body
is then sent piece by piece (runtime/rest.py ``MultipartBody``): a file is read from
its temporary file in pieces of ``SEND_CHUNK_BYTES`` while it is sent, so the process
holds about one piece in memory, not the files.

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
import tempfile
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from typing import IO, Any

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
KIB = 1024
MIB = 1024 * KIB
MAX_STICKER_BYTES = 512 * KIB
MAX_FILES = 10
#: Discord's default upload limit, per file (discord-api-docs 9b737ec, developers/
#: reference.mdx, "Uploading Files"); the documentation names no limit per request.
MAX_FILE_BYTES = 20 * MIB
#: Pieces a workflow file is read in from storage and sent in (the SDK's default chunk).
READ_CHUNK_BYTES = MIB
SEND_CHUNK_BYTES = MIB


def size_text(count: int) -> str:
    """A byte count as messages show it (``20 MiB``), from the constant the check uses."""
    if count % MIB == 0:
        return f"{count // MIB} MiB"
    if count % KIB == 0:
        return f"{count // KIB} KiB"
    return f"{count} bytes"


@dataclass(frozen=True)
class Part:
    """One file of a multipart body: its bytes (a base64 file), or a temporary file
    holding a workflow file, read piece by piece when it is sent."""

    name: str
    filename: str
    content_type: str
    data: bytes | None = field(default=None, repr=False)
    source: IO[bytes] | None = field(default=None, repr=False)
    size: int = 0

    def chunks(self) -> Iterator[bytes]:
        if self.source is None:
            yield self.data or b""
            return
        self.source.seek(0)
        while chunk := self.source.read(SEND_CHUNK_BYTES):
            yield chunk

    def close(self) -> None:
        if self.source is not None:
            self.source.close()


def extension_of(filename: str) -> str:
    dot = filename.rfind(".")
    return filename[dot:].lower() if dot > 0 else ""


def content_type_for(filename: str) -> str:
    return CONTENT_TYPES.get(extension_of(filename), DEFAULT_CONTENT_TYPE)


#: A workflow file by its handle, as pieces of bytes (the SDK's stream_artifact_bytes).
ArtifactReader = Callable[[str], Iterable[bytes]]


class _TooLarge(ValueError):
    """A file larger than its limit; the message says which."""


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
    try:
        _collect(operation_id, files, artifacts, parts, read_artifact, valid_name)
    except BaseException:
        for part in parts:
            part.close()
        raise
    return parts


def _collect(
    operation_id: str,
    files: list[Any],
    artifacts: list[Any],
    parts: list[Part],
    read_artifact: ArtifactReader | None,
    valid_name: Callable[[str], bool],
) -> None:
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
        limit = _limit(operation_id, entry["filename"])
        source, size = _spool(read_artifact, handle.strip(), limit)
        parts.append(
            Part(
                entry["field"],
                entry["filename"],
                content_type_for(entry["filename"]),
                source=source,
                size=size,
            )
        )
    if len({part.name for part in parts}) != len(parts):
        raise ValueError("Duplicate multipart file field")


def _spool(read_artifact: ArtifactReader, handle: str, limit: int) -> tuple[IO[bytes], int]:
    """A workflow file copied to a temporary file (deleted when closed), and its size;
    it stops as soon as the file is larger than ``limit``."""
    sink = tempfile.TemporaryFile()  # noqa: SIM115 - closed by Part.close
    total = 0
    try:
        for chunk in read_artifact(handle):
            total += len(chunk)
            if total > limit:
                raise _TooLarge(_too_large(limit))
            sink.write(chunk)
    except _TooLarge:
        sink.close()
        raise
    except Exception:  # noqa: BLE001 - any read failure: nothing was sent
        sink.close()
        raise ValueError("The workflow file could not be read") from None
    return sink, total


def _limit(operation_id: str, filename: str) -> int:
    if operation_id == STICKER_OPERATION:
        if extension_of(filename) not in STICKER_EXTENSIONS:
            raise ValueError("A sticker must be a PNG, APNG, GIF or Lottie JSON file")
        return MAX_STICKER_BYTES
    return MAX_FILE_BYTES


def _too_large(limit: int) -> str:
    if limit == MAX_STICKER_BYTES:
        return f"A sticker file is larger than {size_text(MAX_STICKER_BYTES)}"
    return f"A file is larger than {size_text(MAX_FILE_BYTES)}, Discord's upload limit per file"


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
    limit = _limit(operation_id, filename)
    if len(content) > limit:
        raise ValueError(_too_large(limit))
    return Part(name, filename, content_type_for(filename), data=content, size=len(content))
