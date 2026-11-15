"""Unit tests for provenance primitives."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pyroharmonize.provenance import (
    compute_data_hash,
    count_jsonl_lines,
    safe_zip_target,
    sha256_bytes,
    sha256_file,
    write_json,
)


def test_sha256_known_vector() -> None:
    assert sha256_bytes(b"abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


def test_sha256_file_matches_bytes(tmp_path: Path) -> None:
    payload = b"pyroharmonize provenance"
    path = tmp_path / "sample.bin"
    path.write_bytes(payload)
    assert sha256_file(path) == sha256_bytes(payload)


def test_compute_data_hash_is_order_sensitive() -> None:
    digests = {"MODIS": "aa", "VIIRS_SNPP": "bb", "VIIRS_NOAA20": "cc"}
    assert compute_data_hash(digests, ("MODIS", "VIIRS_SNPP", "VIIRS_NOAA20")) == sha256_bytes(
        b"aabbcc"
    )
    assert compute_data_hash(digests, ("VIIRS_SNPP", "MODIS", "VIIRS_NOAA20")) == sha256_bytes(
        b"bbaacc"
    )


def test_compute_data_hash_refuses_missing_sensor() -> None:
    with pytest.raises(KeyError):
        compute_data_hash({"MODIS": "aa"}, ("MODIS", "VIIRS_SNPP"))


def test_safe_zip_target_rejects_traversal(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        safe_zip_target(tmp_path, "../escaped.txt")
    with pytest.raises(ValueError):
        safe_zip_target(tmp_path, "/absolute.txt")


def test_safe_zip_target_accepts_normal_member(tmp_path: Path) -> None:
    target = safe_zip_target(tmp_path, "data/raw/file.csv")
    assert target == (tmp_path / "data" / "raw" / "file.csv").resolve()


def test_count_jsonl_lines_handles_trailing_newline(tmp_path: Path) -> None:
    with_newline = tmp_path / "a.jsonl"
    with_newline.write_bytes(b'{"a": 1}\n{"a": 2}\n')
    assert count_jsonl_lines(with_newline) == 2

    without_newline = tmp_path / "b.jsonl"
    without_newline.write_bytes(b'{"a": 1}\n{"a": 2}')
    assert count_jsonl_lines(without_newline) == 2

    empty = tmp_path / "c.jsonl"
    empty.write_bytes(b"")
    assert count_jsonl_lines(empty) == 0


def test_write_json_is_sorted_and_newline_terminated(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "payload.json"
    write_json(path, {"b": 2, "a": 1})
    text = path.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert json.loads(text) == {"a": 1, "b": 2}
    assert text.index('"a"') < text.index('"b"')
