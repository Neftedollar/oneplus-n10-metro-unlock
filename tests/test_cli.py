from __future__ import annotations

import json
from pathlib import Path

from oneplus_n10_param.cli import main
from oneplus_n10_param.core import PARAM_SIZE, inspect_param


def test_inspect_cli_emits_valid_json(
    tmp_path: Path,
    pristine_param: bytes,
    synthetic_serial: int,
    capsys,
) -> None:
    source = tmp_path / "param.bin"
    source.write_bytes(pristine_param)
    status = main([
        "inspect",
        str(source),
        "--soc-serial",
        hex(synthetic_serial),
        "--json",
    ])
    assert status == 0
    report = json.loads(capsys.readouterr().out)
    assert report["state"] == "metro-pristine"
    assert report["duplicates_match"] is True
    assert "serial" not in report
    assert "key" not in report


def test_patch_cli_is_dry_run_without_output(
    tmp_path: Path,
    pristine_param: bytes,
    synthetic_serial: int,
    capsys,
) -> None:
    source = tmp_path / "param.bin"
    source.write_bytes(pristine_param)
    status = main([
        "patch-global",
        str(source),
        "--soc-serial",
        hex(synthetic_serial),
        "--json",
    ])
    assert status == 0
    report = json.loads(capsys.readouterr().out)
    assert report["dry_run"] is True
    assert report["output"] is None
    assert sorted(path.name for path in tmp_path.iterdir()) == ["param.bin"]


def test_patch_cli_writes_only_with_explicit_output(
    tmp_path: Path,
    pristine_param: bytes,
    synthetic_serial: int,
    capsys,
) -> None:
    source = tmp_path / "param.bin"
    output = tmp_path / "global-trigger.bin"
    source.write_bytes(pristine_param)
    status = main([
        "patch-global",
        str(source),
        "--soc-serial",
        hex(synthetic_serial),
        "--output",
        str(output),
        "--json",
    ])
    assert status == 0
    report = json.loads(capsys.readouterr().out)
    assert report["dry_run"] is False
    assert output.stat().st_size == PARAM_SIZE
    assert inspect_param(output.read_bytes(), synthetic_serial).state == "global-trigger"
    assert source.read_bytes() == pristine_param


def test_rollback_cli_generates_metro_trigger(
    tmp_path: Path,
    pristine_param: bytes,
    synthetic_serial: int,
    capsys,
) -> None:
    source = tmp_path / "param.bin"
    output = tmp_path / "rollback.bin"
    source.write_bytes(pristine_param)
    assert main([
        "rollback-trigger",
        str(source),
        "--soc-serial",
        hex(synthetic_serial),
        "--output",
        str(output),
        "--json",
    ]) == 0
    capsys.readouterr()
    assert inspect_param(output.read_bytes(), synthetic_serial).state == "metro-rollback-trigger"


def test_cli_refuses_in_place_output_even_with_overwrite(
    tmp_path: Path,
    pristine_param: bytes,
    synthetic_serial: int,
    capsys,
) -> None:
    source = tmp_path / "param.bin"
    source.write_bytes(pristine_param)
    status = main([
        "patch-global",
        str(source),
        "--soc-serial",
        hex(synthetic_serial),
        "--output",
        str(source),
        "--overwrite",
    ])
    captured = capsys.readouterr()
    assert status == 2
    assert "in place" in captured.err
    assert source.read_bytes() == pristine_param


def test_cli_refuses_existing_output_without_overwrite(
    tmp_path: Path,
    pristine_param: bytes,
    synthetic_serial: int,
    capsys,
) -> None:
    source = tmp_path / "param.bin"
    output = tmp_path / "existing.bin"
    source.write_bytes(pristine_param)
    output.write_bytes(b"\x33" * PARAM_SIZE)
    status = main([
        "patch-global",
        str(source),
        "--soc-serial",
        hex(synthetic_serial),
        "--output",
        str(output),
    ])
    assert status == 2
    assert "already exists" in capsys.readouterr().err
    assert output.read_bytes() == b"\x33" * PARAM_SIZE


def test_cli_requires_output_when_overwrite_is_requested(
    tmp_path: Path,
    pristine_param: bytes,
    synthetic_serial: int,
    capsys,
) -> None:
    source = tmp_path / "param.bin"
    source.write_bytes(pristine_param)
    status = main([
        "patch-global",
        str(source),
        "--soc-serial",
        hex(synthetic_serial),
        "--overwrite",
    ])
    assert status == 2
    assert "requires --output" in capsys.readouterr().err


def test_cli_wrong_serial_fails_without_creating_output(
    tmp_path: Path,
    pristine_param: bytes,
    synthetic_serial: int,
    capsys,
) -> None:
    source = tmp_path / "param.bin"
    output = tmp_path / "must-not-exist.bin"
    source.write_bytes(pristine_param)
    status = main([
        "patch-global",
        str(source),
        "--soc-serial",
        hex(synthetic_serial ^ 1),
        "--output",
        str(output),
    ])
    captured = capsys.readouterr()
    assert status == 2
    assert "inner MD5 mismatch" in captured.err
    assert not output.exists()


def test_cli_counter_ff_fails_without_creating_output(
    tmp_path: Path,
    param_factory,
    synthetic_serial: int,
    capsys,
) -> None:
    source = tmp_path / "counter-exhausted.bin"
    output = tmp_path / "must-not-exist.bin"
    source.write_bytes(param_factory(counter=0xFF))
    status = main([
        "patch-global",
        str(source),
        "--soc-serial",
        hex(synthetic_serial),
        "--output",
        str(output),
    ])
    captured = capsys.readouterr()
    assert status == 2
    assert "counter exhausted at 0xFF; refusing to wrap" in captured.err
    assert not output.exists()
