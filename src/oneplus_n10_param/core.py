"""Strict, offline-only handling of the two BE2025 software-ID SID records.

This module only transforms byte strings and ordinary files.  It contains no
ADB, fastboot, EDL, block-device, or USB integration.
"""

from __future__ import annotations

import hashlib
import os
import struct
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal

from Crypto.Cipher import AES


PARAM_SIZE: Final = 0x100000
SID_SIZE: Final = 0x1000
SID_OFFSETS: Final = (0x4F000, 0xCF000)

MAGIC: Final = 0xA0AD646A
EXPECTED_HEADER_VERSION: Final = 1
EXPECTED_CRYPTO_VERSION: Final = 2
AES_IV: Final = bytes.fromhex("562E17996D093D28DDB3BA695A2E6F58")

ENCRYPTED_OFFSET: Final = 0x400
ENCRYPTED_SIZE: Final = 0xC00
OUTER_MD5_OFFSET: Final = 0x80
INNER_MD5_SIZE: Final = 0x10
ITEM_SIZE: Final = 0xB80
ITEM_OFFSET_IN_CLEAR: Final = ENCRYPTED_SIZE - ITEM_SIZE

METRO_SWID: Final = 0x3A403A71
GLOBAL_SWID: Final = 0xB8BD9E39
PROC_CLEAR: Final = 0
PROC_TRIGGER: Final = 0xDC9EF893

TriggerKind = Literal["global", "rollback"]

_KNOWN_STATES: Final = {
    (METRO_SWID, PROC_CLEAR): "metro-pristine",
    (GLOBAL_SWID, PROC_CLEAR): "global-settled",
    (GLOBAL_SWID, PROC_TRIGGER): "global-trigger",
    (METRO_SWID, PROC_TRIGGER): "metro-rollback-trigger",
}


class ParamValidationError(ValueError):
    """Raised when an input fails a structural or cryptographic invariant."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ParamValidationError(message)


def _md5(data: bytes) -> bytes:
    # MD5 is mandated by the legacy on-disk format, not used as a new security
    # design choice.  usedforsecurity=False also permits validation on FIPS hosts.
    return hashlib.md5(data, usedforsecurity=False).digest()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def derive_aes_key(soc_serial: int) -> bytes:
    """Derive the AES-128 key from an unsigned 32-bit SoC serial.

    The verified BE2025 construction hashes the 26 *ASCII hex characters*;
    they must not be hex-decoded before SHA-256.
    """

    _require(isinstance(soc_serial, int) and not isinstance(soc_serial, bool),
             "SoC serial must be an integer")
    _require(0 <= soc_serial <= 0xFFFFFFFF,
             "SoC serial must be an unsigned 32-bit value")
    material = f"a9264fbf8a{soc_serial:08x}6b4487ea".encode("ascii")
    _require(len(material) == 0x1A, "internal key-derivation length mismatch")
    return hashlib.sha256(material).digest()[:16]


def _aes_decrypt(ciphertext: bytes, key: bytes) -> bytes:
    _require(len(key) == 16, "derived AES key has an invalid length")
    _require(len(ciphertext) == ENCRYPTED_SIZE, "encrypted SID payload has an invalid size")
    return AES.new(key, AES.MODE_CBC, AES_IV).decrypt(ciphertext)


def _aes_encrypt(cleartext: bytes, key: bytes) -> bytes:
    _require(len(key) == 16, "derived AES key has an invalid length")
    _require(len(cleartext) == ENCRYPTED_SIZE, "clear SID payload has an invalid size")
    return AES.new(key, AES.MODE_CBC, AES_IV).encrypt(cleartext)


@dataclass(frozen=True)
class SidRecord:
    offset: int
    header_version: int
    crypto_version: int
    counter: int
    supported: int
    swid: int
    proc: int
    state: str
    block: bytes = field(repr=False)
    cleartext: bytes = field(repr=False)
    item_data: bytes = field(repr=False)

    def public_dict(self) -> dict[str, int | str]:
        return {
            "offset": f"0x{self.offset:05X}",
            "header_version": self.header_version,
            "crypto_version": self.crypto_version,
            "counter": self.counter,
            "supported": self.supported,
            "swid": f"0x{self.swid:08X}",
            "proc": f"0x{self.proc:08X}",
            "state": self.state,
        }


@dataclass(frozen=True)
class Inspection:
    source_sha256: str
    size: int
    state: str
    records: tuple[SidRecord, SidRecord]

    def public_dict(self) -> dict[str, object]:
        return {
            "source_sha256": self.source_sha256,
            "size": self.size,
            "state": self.state,
            "duplicates_match": True,
            "records": [record.public_dict() for record in self.records],
        }


@dataclass(frozen=True)
class PatchResult:
    kind: TriggerKind
    data: bytes = field(repr=False)
    source_sha256: str
    output_sha256: str
    changed_bytes: int
    source_counter: int
    output_counter: int
    target_swid: int
    target_proc: int
    output_state: str

    def public_dict(self, *, wrote_output: bool, output: Path | None) -> dict[str, object]:
        return {
            "action": f"{self.kind}-trigger",
            "dry_run": not wrote_output,
            "source_sha256": self.source_sha256,
            "output_sha256": self.output_sha256,
            "size": len(self.data),
            "changed_bytes": self.changed_bytes,
            "changed_ranges": ["0x4F000-0x4FFFF", "0xCF000-0xCFFFF"],
            "source_counter": self.source_counter,
            "output_counter": self.output_counter,
            "target_swid": f"0x{self.target_swid:08X}",
            "target_proc": f"0x{self.target_proc:08X}",
            "output_state": self.output_state,
            "roundtrip_verification": "passed",
            "output": str(output) if wrote_output and output is not None else None,
        }


def _parse_sid(block: bytes, offset: int, key: bytes) -> SidRecord:
    label = f"SID at 0x{offset:05X}"
    _require(len(block) == SID_SIZE, f"{label}: invalid block size")

    magic, header_version, crypto_version = struct.unpack_from("<IBB", block, 0)
    _require(magic == MAGIC, f"{label}: invalid magic 0x{magic:08X}")
    _require(header_version == EXPECTED_HEADER_VERSION,
             f"{label}: unexpected header version {header_version}")
    _require(crypto_version == EXPECTED_CRYPTO_VERSION,
             f"{label}: unexpected crypto version {crypto_version}")

    counter = block[0x10]
    ciphertext = block[ENCRYPTED_OFFSET:ENCRYPTED_OFFSET + ENCRYPTED_SIZE]
    stored_outer = block[OUTER_MD5_OFFSET:OUTER_MD5_OFFSET + INNER_MD5_SIZE]
    _require(_md5(ciphertext) == stored_outer, f"{label}: outer MD5 mismatch")

    cleartext = _aes_decrypt(ciphertext, key)
    item_data = cleartext[ITEM_OFFSET_IN_CLEAR:]
    _require(len(item_data) == ITEM_SIZE, f"{label}: invalid decrypted item size")
    _require(_md5(item_data) == cleartext[:INNER_MD5_SIZE],
             f"{label}: inner MD5 mismatch (wrong SoC serial or corrupted data)")

    supported, swid, proc = struct.unpack_from("<III", item_data, 0)
    _require(supported == 1, f"{label}: unsupported SoftwareProjectID record ({supported})")
    state = _KNOWN_STATES.get((swid, proc))
    _require(state is not None,
             f"{label}: unexpected SWID/proc pair 0x{swid:08X}/0x{proc:08X}")

    return SidRecord(
        offset=offset,
        header_version=header_version,
        crypto_version=crypto_version,
        counter=counter,
        supported=supported,
        swid=swid,
        proc=proc,
        state=state,
        block=block,
        cleartext=cleartext,
        item_data=item_data,
    )


def inspect_param(data: bytes, soc_serial: int) -> Inspection:
    """Validate a complete 1 MiB image and both duplicate SWID records."""

    _require(isinstance(data, bytes), "param image must be immutable bytes")
    _require(len(data) == PARAM_SIZE,
             f"param image must be exactly {PARAM_SIZE} bytes; got {len(data)}")
    key = derive_aes_key(soc_serial)
    records = tuple(
        _parse_sid(data[offset:offset + SID_SIZE], offset, key)
        for offset in SID_OFFSETS
    )
    primary, backup = records

    _require(primary.counter == backup.counter,
             f"SID counter mismatch: {primary.counter} != {backup.counter}")
    _require(primary.header_version == backup.header_version,
             "SID header-version mismatch")
    _require(primary.crypto_version == backup.crypto_version,
             "SID crypto-version mismatch")
    _require((primary.swid, primary.proc) == (backup.swid, backup.proc),
             "duplicate SWID/proc mismatch")
    _require(primary.item_data == backup.item_data,
             "duplicate decrypted payload mismatch")
    _require(primary.block == backup.block,
             "duplicate SID blocks are not byte-identical")
    _require(primary.state == backup.state, "duplicate SID state mismatch")

    return Inspection(
        source_sha256=_sha256(data),
        size=len(data),
        state=primary.state,
        records=(primary, backup),
    )


def _patch_sid(record: SidRecord, key: bytes, target_swid: int) -> bytes:
    _require(record.counter < 0xFF,
             f"SID at 0x{record.offset:05X}: counter exhausted at 0xFF; refusing to wrap")
    item_data = bytearray(record.item_data)
    struct.pack_into("<I", item_data, 4, target_swid)
    struct.pack_into("<I", item_data, 8, PROC_TRIGGER)

    cleartext = bytearray(record.cleartext)
    cleartext[ITEM_OFFSET_IN_CLEAR:] = item_data
    cleartext[:INNER_MD5_SIZE] = _md5(bytes(item_data))
    ciphertext = _aes_encrypt(bytes(cleartext), key)

    result = bytearray(record.block)
    result[0x10] = record.counter + 1
    result[OUTER_MD5_OFFSET:OUTER_MD5_OFFSET + INNER_MD5_SIZE] = _md5(ciphertext)
    result[ENCRYPTED_OFFSET:ENCRYPTED_OFFSET + ENCRYPTED_SIZE] = ciphertext
    return bytes(result)


def _assert_change_scope(before: bytes, after: bytes) -> int:
    _require(len(before) == len(after) == PARAM_SIZE, "patch changed the image size")
    allowed = tuple(
        part
        for base in SID_OFFSETS
        for part in (
            (base + 0x10, base + 0x11),
            (base + OUTER_MD5_OFFSET, base + OUTER_MD5_OFFSET + INNER_MD5_SIZE),
            (base + ENCRYPTED_OFFSET, base + SID_SIZE),
        )
    )
    changed = 0
    for index, (old, new) in enumerate(zip(before, after)):
        if old == new:
            continue
        changed += 1
        _require(any(start <= index < end for start, end in allowed),
                 f"patch changed a byte outside permitted fields at 0x{index:X}")
    _require(changed > 0, "patch produced no changes")
    return changed


def build_trigger(data: bytes, soc_serial: int, kind: TriggerKind) -> PatchResult:
    """Build and round-trip verify a Global or Metro rollback trigger image.

    Both operations intentionally require the same pristine Metro source.  This
    prevents an already-triggered, settled-Global, or otherwise modified image
    from being silently used as a patch base.
    """

    _require(kind in ("global", "rollback"), f"unsupported trigger kind: {kind!r}")
    source = inspect_param(data, soc_serial)
    _require(source.state == "metro-pristine",
             f"patch source must be metro-pristine; got {source.state}")
    _require(source.records[0].counter < 0xFF,
             "SID counter exhausted at 0xFF; refusing to wrap")

    target_swid = GLOBAL_SWID if kind == "global" else METRO_SWID
    key = derive_aes_key(soc_serial)
    patched = bytearray(data)
    for record in source.records:
        patched[record.offset:record.offset + SID_SIZE] = _patch_sid(record, key, target_swid)
    output = bytes(patched)

    changed_bytes = _assert_change_scope(data, output)
    verified = inspect_param(output, soc_serial)
    expected_state = "global-trigger" if kind == "global" else "metro-rollback-trigger"
    expected_counter = source.records[0].counter + 1
    _require(verified.state == expected_state,
             f"round-trip state mismatch: {verified.state} != {expected_state}")
    _require(all(record.counter == expected_counter for record in verified.records),
             "round-trip counter mismatch")
    _require(all((record.supported, record.swid, record.proc)
                 == (1, target_swid, PROC_TRIGGER) for record in verified.records),
             "round-trip SWID/proc mismatch")

    return PatchResult(
        kind=kind,
        data=output,
        source_sha256=source.source_sha256,
        output_sha256=_sha256(output),
        changed_bytes=changed_bytes,
        source_counter=source.records[0].counter,
        output_counter=expected_counter,
        target_swid=target_swid,
        target_proc=PROC_TRIGGER,
        output_state=verified.state,
    )


def read_param_file(path: Path) -> bytes:
    """Read exactly one 1 MiB regular-file image, rejecting all other sizes."""

    path = Path(path)
    _require(path.is_file(), f"input is not a regular file: {path}")
    size = path.stat().st_size
    _require(size == PARAM_SIZE,
             f"param image must be exactly {PARAM_SIZE} bytes; got {size}")
    with path.open("rb") as stream:
        data = stream.read(PARAM_SIZE + 1)
    _require(len(data) == PARAM_SIZE, "input size changed while it was being read")
    return data


def _fsync_directory(directory: Path) -> None:
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def atomic_write(path: Path, data: bytes, *, overwrite: bool = False) -> None:
    """Atomically create or replace an offline output image.

    Without ``overwrite``, a same-directory hard link provides atomic
    create-if-absent semantics and closes the usual exists-check race.
    """

    path = Path(path)
    _require(len(data) == PARAM_SIZE,
             f"refusing to write output of unexpected size {len(data)}")
    parent = path.parent
    _require(parent.is_dir(), f"output directory does not exist: {parent}")
    _require(not path.is_symlink(), f"refusing a symlink output path: {path}")
    _require(not path.is_dir(), f"output path is a directory: {path}")
    _require(not path.exists() or path.is_file(),
             f"refusing a non-regular output path: {path}")

    descriptor, temporary_name = tempfile.mkstemp(
        dir=parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    installed = False
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            descriptor = -1
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())

        if overwrite:
            os.replace(temporary, path)
            installed = True
        else:
            try:
                os.link(temporary, path)
            except FileExistsError as error:
                raise ParamValidationError(
                    f"output already exists (use --overwrite explicitly): {path}"
                ) from error
            installed = True
            temporary.unlink()

        _fsync_directory(parent)
        written = read_param_file(path)
        _require(_sha256(written) == _sha256(data), "atomic output verification failed")
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()
        if not installed:
            _fsync_directory(parent)


def ensure_distinct_paths(input_path: Path, output_path: Path) -> None:
    """Reject in-place operation even when aliases or symlinks are involved."""

    input_path = Path(input_path)
    output_path = Path(output_path)
    if output_path.exists():
        try:
            _require(not os.path.samefile(input_path, output_path),
                     "refusing to overwrite the input image in place")
        except FileNotFoundError:
            pass
    _require(input_path.resolve() != output_path.resolve(),
             "refusing to overwrite the input image in place")
