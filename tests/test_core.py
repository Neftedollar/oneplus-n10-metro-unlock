from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

import pytest

from oneplus_n10_param.core import (
    GLOBAL_SWID,
    METRO_SWID,
    PARAM_SIZE,
    PROC_TRIGGER,
    SID_OFFSETS,
    SID_SIZE,
    ParamValidationError,
    atomic_write,
    build_trigger,
    derive_aes_key,
    ensure_distinct_paths,
    inspect_param,
    read_param_file,
)

from conftest import SYNTHETIC_SERIAL, make_sid_block


def test_key_derivation_hashes_ascii_hex_characters() -> None:
    material = b"a9264fbf8a010203046b4487ea"
    expected = hashlib.sha256(material).digest()[:16]
    wrong_hex_decoded = hashlib.sha256(bytes.fromhex(material.decode("ascii"))).digest()[:16]
    assert derive_aes_key(SYNTHETIC_SERIAL) == expected
    assert derive_aes_key(SYNTHETIC_SERIAL) != wrong_hex_decoded


@pytest.mark.parametrize("serial", [-1, 0x1_0000_0000, True, "1"])
def test_key_derivation_rejects_non_u32(serial: object) -> None:
    with pytest.raises(ParamValidationError, match="SoC serial"):
        derive_aes_key(serial)  # type: ignore[arg-type]


def test_inspect_validates_both_exact_duplicates(
    pristine_param: bytes,
    synthetic_serial: int,
) -> None:
    report = inspect_param(pristine_param, synthetic_serial)
    assert report.size == PARAM_SIZE
    assert report.state == "metro-pristine"
    assert [record.offset for record in report.records] == list(SID_OFFSETS)
    assert all(record.counter == 0xFE for record in report.records)
    assert all((record.swid, record.proc) == (METRO_SWID, 0) for record in report.records)
    assert report.records[0].block == report.records[1].block


@pytest.mark.parametrize("size", [0, PARAM_SIZE - 1, PARAM_SIZE + 1])
def test_inspect_rejects_wrong_image_size(size: int, synthetic_serial: int) -> None:
    with pytest.raises(ParamValidationError, match="exactly"):
        inspect_param(b"\0" * size, synthetic_serial)


def test_inspect_requires_immutable_bytes(pristine_param: bytes, synthetic_serial: int) -> None:
    with pytest.raises(ParamValidationError, match="immutable"):
        inspect_param(bytearray(pristine_param), synthetic_serial)  # type: ignore[arg-type]


def test_outer_md5_corruption_fails_closed(
    pristine_param: bytes,
    synthetic_serial: int,
) -> None:
    damaged = bytearray(pristine_param)
    damaged[SID_OFFSETS[0] + 0x80] ^= 1
    with pytest.raises(ParamValidationError, match="outer MD5 mismatch"):
        inspect_param(bytes(damaged), synthetic_serial)


def test_bad_magic_fails_closed(pristine_param: bytes, synthetic_serial: int) -> None:
    damaged = bytearray(pristine_param)
    damaged[SID_OFFSETS[0]] ^= 1
    with pytest.raises(ParamValidationError, match="invalid magic"):
        inspect_param(bytes(damaged), synthetic_serial)


def test_wrong_serial_fails_inner_md5(pristine_param: bytes, synthetic_serial: int) -> None:
    with pytest.raises(ParamValidationError, match="inner MD5 mismatch"):
        inspect_param(pristine_param, synthetic_serial ^ 1)


@pytest.mark.parametrize(
    ("swid", "proc"),
    [(0x11223344, 0), (METRO_SWID, 0x55667788)],
)
def test_unknown_swid_or_proc_fails_closed(
    param_factory,
    synthetic_serial: int,
    swid: int,
    proc: int,
) -> None:
    image = param_factory(swid=swid, proc=proc)
    with pytest.raises(ParamValidationError, match="unexpected SWID/proc"):
        inspect_param(image, synthetic_serial)


def test_unsupported_swid_record_fails_closed(param_factory, synthetic_serial: int) -> None:
    image = param_factory(supported=0)
    with pytest.raises(ParamValidationError, match="unsupported SoftwareProjectID"):
        inspect_param(image, synthetic_serial)


def test_counter_mismatch_is_reported_before_generic_duplicate_failure(
    param_factory,
    synthetic_serial: int,
) -> None:
    primary = make_sid_block(counter=8)
    backup = make_sid_block(counter=9)
    image = param_factory(primary=primary, backup=backup)
    with pytest.raises(ParamValidationError, match="SID counter mismatch"):
        inspect_param(image, synthetic_serial)


def test_nonsemantic_duplicate_difference_fails_closed(
    pristine_param: bytes,
    synthetic_serial: int,
) -> None:
    damaged = bytearray(pristine_param)
    damaged[SID_OFFSETS[1] + 0x20] ^= 1
    with pytest.raises(ParamValidationError, match="not byte-identical"):
        inspect_param(bytes(damaged), synthetic_serial)


def test_decrypted_duplicate_difference_fails_closed(param_factory, synthetic_serial: int) -> None:
    image = param_factory(
        primary=make_sid_block(payload_tweak=0),
        backup=make_sid_block(payload_tweak=1),
    )
    with pytest.raises(ParamValidationError, match="decrypted payload mismatch"):
        inspect_param(image, synthetic_serial)


def test_duplicate_swid_proc_difference_fails_closed(param_factory, synthetic_serial: int) -> None:
    image = param_factory(
        primary=make_sid_block(swid=METRO_SWID, proc=0),
        backup=make_sid_block(swid=GLOBAL_SWID, proc=0),
    )
    with pytest.raises(ParamValidationError, match="duplicate SWID/proc mismatch"):
        inspect_param(image, synthetic_serial)


@pytest.mark.parametrize(
    ("field", "block"),
    [
        ("header version", make_sid_block(header_version=3)),
        ("crypto version", make_sid_block(crypto_version=7)),
    ],
)
def test_unexpected_header_variant_fails_closed(
    param_factory,
    synthetic_serial: int,
    field: str,
    block: bytes,
) -> None:
    with pytest.raises(ParamValidationError, match=field):
        inspect_param(param_factory(primary=block, backup=block), synthetic_serial)


def _assert_only_allowed_fields_changed(before: bytes, after: bytes) -> None:
    allowed = tuple(
        span
        for base in SID_OFFSETS
        for span in (
            (base + 0x10, base + 0x11),
            (base + 0x80, base + 0x90),
            (base + 0x400, base + SID_SIZE),
        )
    )
    changed = [
        index
        for index, pair in enumerate(zip(before, after))
        if pair[0] != pair[1]
    ]
    assert changed
    assert all(any(start <= index < end for start, end in allowed) for index in changed)


def test_global_trigger_is_roundtrip_verified_and_narrowly_scoped(
    pristine_param: bytes,
    synthetic_serial: int,
) -> None:
    result = build_trigger(pristine_param, synthetic_serial, "global")
    assert len(result.data) == PARAM_SIZE
    assert result.target_swid == GLOBAL_SWID
    assert result.target_proc == PROC_TRIGGER
    assert result.source_counter == 0xFE
    assert result.output_counter == 0xFF
    assert result.output_state == "global-trigger"
    assert pristine_param[SID_OFFSETS[0] + 0x14] == result.data[SID_OFFSETS[0] + 0x14]
    _assert_only_allowed_fields_changed(pristine_param, result.data)
    verified = inspect_param(result.data, synthetic_serial)
    assert verified.state == "global-trigger"
    assert all((record.swid, record.proc) == (GLOBAL_SWID, PROC_TRIGGER)
               for record in verified.records)


def test_rollback_trigger_preserves_metro_swid(
    pristine_param: bytes,
    synthetic_serial: int,
) -> None:
    result = build_trigger(pristine_param, synthetic_serial, "rollback")
    assert result.target_swid == METRO_SWID
    assert result.output_state == "metro-rollback-trigger"
    verified = inspect_param(result.data, synthetic_serial)
    assert all((record.swid, record.proc) == (METRO_SWID, PROC_TRIGGER)
               for record in verified.records)


def test_counter_ff_fails_closed_without_wrapping(param_factory, synthetic_serial: int) -> None:
    source = param_factory(counter=0xFF)
    with pytest.raises(ParamValidationError, match="counter exhausted at 0xFF; refusing to wrap"):
        build_trigger(source, synthetic_serial, "global")
    assert all(record.counter == 0xFF for record in inspect_param(source, synthetic_serial).records)


def test_patch_rejects_nonpristine_known_state(param_factory, synthetic_serial: int) -> None:
    already_triggered = param_factory(swid=GLOBAL_SWID, proc=PROC_TRIGGER)
    with pytest.raises(ParamValidationError, match="must be metro-pristine"):
        build_trigger(already_triggered, synthetic_serial, "global")


def test_atomic_create_is_private_verified_and_leaves_no_temp(
    tmp_path: Path,
    pristine_param: bytes,
) -> None:
    output = tmp_path / "patched.bin"
    atomic_write(output, pristine_param)
    assert read_param_file(output) == pristine_param
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert list(tmp_path.glob(".patched.bin.*.tmp")) == []


def test_atomic_write_refuses_existing_output_without_overwrite(
    tmp_path: Path,
    pristine_param: bytes,
) -> None:
    output = tmp_path / "existing.bin"
    original = b"\x11" * PARAM_SIZE
    output.write_bytes(original)
    with pytest.raises(ParamValidationError, match="already exists"):
        atomic_write(output, pristine_param)
    assert output.read_bytes() == original
    assert list(tmp_path.glob(".existing.bin.*.tmp")) == []


def test_atomic_create_failure_cleans_temporary_file(
    tmp_path: Path,
    pristine_param: bytes,
    monkeypatch,
) -> None:
    output = tmp_path / "failed.bin"

    def fail_link(_source, _destination) -> None:
        raise OSError("synthetic link failure")

    monkeypatch.setattr(os, "link", fail_link)
    with pytest.raises(OSError, match="synthetic link failure"):
        atomic_write(output, pristine_param)
    assert not output.exists()
    assert list(tmp_path.glob(".failed.bin.*.tmp")) == []


def test_atomic_overwrite_must_be_explicit(tmp_path: Path, pristine_param: bytes) -> None:
    output = tmp_path / "existing.bin"
    output.write_bytes(b"\x11" * PARAM_SIZE)
    atomic_write(output, pristine_param, overwrite=True)
    assert output.read_bytes() == pristine_param


def test_atomic_write_rejects_wrong_size(tmp_path: Path) -> None:
    with pytest.raises(ParamValidationError, match="unexpected size"):
        atomic_write(tmp_path / "short.bin", b"short")


def test_atomic_write_rejects_symlink_output(tmp_path: Path, pristine_param: bytes) -> None:
    target = tmp_path / "target.bin"
    target.write_bytes(b"\x22" * PARAM_SIZE)
    link = tmp_path / "link.bin"
    link.symlink_to(target)
    with pytest.raises(ParamValidationError, match="symlink"):
        atomic_write(link, pristine_param, overwrite=True)
    assert target.read_bytes() == b"\x22" * PARAM_SIZE


def test_read_param_file_checks_regular_file_and_size(tmp_path: Path) -> None:
    with pytest.raises(ParamValidationError, match="regular file"):
        read_param_file(tmp_path)
    short = tmp_path / "short.bin"
    short.write_bytes(b"short")
    with pytest.raises(ParamValidationError, match="exactly"):
        read_param_file(short)


def test_in_place_output_is_always_rejected(tmp_path: Path, pristine_param: bytes) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(pristine_param)
    with pytest.raises(ParamValidationError, match="in place"):
        ensure_distinct_paths(source, source)
    alias = tmp_path / "alias.bin"
    os.link(source, alias)
    with pytest.raises(ParamValidationError, match="in place"):
        ensure_distinct_paths(source, alias)
