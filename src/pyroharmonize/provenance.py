"""Hashing, archive inspection, and manifest verification.

The functions here are pure with respect to the input files: they read bytes
and return values, and never modify data.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import zipfile
from pathlib import Path
from typing import Iterable, Sequence

CHUNK_SIZE = 8 * 1024 * 1024


def sha256_file(path: str | Path, chunk_size: int = CHUNK_SIZE) -> str:
    """Return the SHA-256 hex digest of a file, read in bounded chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def compute_data_hash(per_file_digests: dict[str, str], sensor_order: Sequence[str]) -> str:
    """Implement the documented data_hash definition.

    SHA-256 over the ASCII concatenation of the per-file hex digests taken in
    the given sensor order. Raises if a sensor is missing so an incomplete
    dictionary can never silently produce a plausible hash.
    """
    missing = [sensor for sensor in sensor_order if sensor not in per_file_digests]
    if missing:
        raise KeyError(f"missing digests for sensors: {missing}")
    concatenated = "".join(per_file_digests[sensor] for sensor in sensor_order)
    return hashlib.sha256(concatenated.encode("ascii")).hexdigest()


def read_zip_manifest(zip_path: str | Path) -> list[dict[str, object]]:
    """Hash every file entry in a ZIP without extracting it.

    Directory entries are skipped. The result is ordered as stored in the
    archive.
    """
    entries: list[dict[str, object]] = []
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            digest = hashlib.sha256()
            with archive.open(info) as handle:
                for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
                    digest.update(chunk)
            entries.append(
                {
                    "path": info.filename,
                    "bytes": info.file_size,
                    "compressed_bytes": info.compress_size,
                    "crc32": f"{info.CRC:08x}",
                    "sha256": digest.hexdigest(),
                }
            )
    return entries


def safe_zip_target(destination: Path, member_name: str) -> Path:
    """Resolve a ZIP member path and reject absolute paths or traversal."""
    destination = destination.resolve()
    target = (destination / member_name).resolve()
    if not target.is_relative_to(destination):
        raise ValueError(f"unsafe archive member escapes destination: {member_name!r}")
    return target


def set_read_only(path: str | Path) -> None:
    """Set the read-only attribute on a file (Windows-safe)."""
    os.chmod(path, stat.S_IREAD)


def is_read_only(path: str | Path) -> bool:
    """Return True when the file is not writable by the current process."""
    return not os.access(path, os.W_OK)


def verify_manifest(manifest: dict, raw_root: str | Path) -> list[str]:
    """Compare every recorded file against disk.

    Returns a list of human-readable discrepancies. An empty list means the
    frozen tree matches the manifest byte for byte.
    """
    root = Path(raw_root).resolve()
    problems: list[str] = []
    recorded = {entry["path"]: entry for entry in manifest["files"]}

    for rel_path, entry in recorded.items():
        path = (root / rel_path).resolve()
        if not path.is_relative_to(root):
            problems.append(f"path escapes raw root: {rel_path}")
            continue
        if not path.is_file():
            problems.append(f"missing: {rel_path}")
            continue
        size = path.stat().st_size
        if size != entry["bytes"]:
            problems.append(f"size mismatch: {rel_path} ({size} != {entry['bytes']})")
            continue
        digest = sha256_file(path)
        if digest != entry["sha256"]:
            problems.append(f"sha256 mismatch: {rel_path}")
        if not is_read_only(path):
            problems.append(f"not read-only: {rel_path}")

    on_disk = {
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file()
    }
    for extra in sorted(on_disk - set(recorded)):
        problems.append(f"unexpected file: {extra}")
    for missing in sorted(set(recorded) - on_disk):
        problems.append(f"missing file: {missing}")

    return problems


def write_json(path: str | Path, payload: dict | list) -> None:
    """Write deterministic JSON (sorted keys, newline-terminated)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8")


def count_jsonl_lines(path: str | Path, chunk_size: int = CHUNK_SIZE) -> int:
    """Count lines in a JSONL file without parsing records."""
    newlines = 0
    last_byte = b""
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            newlines += chunk.count(b"\n")
            last_byte = chunk[-1:]
    if last_byte and last_byte != b"\n":
        newlines += 1
    return newlines


def first_jsonl_record(path: str | Path) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        line = handle.readline()
    if not line.strip():
        raise ValueError(f"empty JSONL file: {path}")
    return json.loads(line)
