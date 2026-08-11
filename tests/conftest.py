from __future__ import annotations

import hashlib
import struct
from collections.abc import Callable

import pytest
from Crypto.Cipher import AES

from oneplus_n10_param.core import (
    MAGIC,
    METRO_SWID,
    PARAM_SIZE,
    PROC_CLEAR,
    SID_OFFSETS,
    SID_SIZE,
)


SYNTHETIC_SERIAL = 0x01020304
TEST_IV = bytes.fromhex("562E17996D093D28DDB3BA695A2E6F58")


def legacy_md5(data: bytes) -> bytes:
    return hashlib.md5(data, usedforsecurity=False).digest()


def independent_key(serial: int) -> bytes:
    material = f"a9264fbf8a{serial:08x}6b4487ea".encode("ascii")
    return hashlib.sha256(material).digest()[:16]


def make_sid_block(
    *,
    serial: int = SYNTHETIC_SERIAL,
    swid: int = METRO_SWID,
    proc: int = PROC_CLEAR,
    counter: int = 0xFE,
    header_version: int = 1,
    crypto_version: int = 2,
    payload_tweak: int = 0,
    supported: int = 1,
) -> bytes:
    item = bytearray(((index * 29 + 7) & 0xFF) for index in range(0xB80))
    struct.pack_into("<III", item, 0, supported, swid, proc)
    item[0x100] ^= payload_tweak

    clear = bytearray(0xC00)
    clear[:16] = legacy_md5(bytes(item))
    clear[0x80:] = item
    encrypted = AES.new(independent_key(serial), AES.MODE_CBC, TEST_IV).encrypt(clear)

    block = bytearray(SID_SIZE)
    struct.pack_into("<IBB", block, 0, MAGIC, header_version, crypto_version)
    block[0x10] = counter
    block[0x14] = 2  # An ignored header byte that production code must preserve.
    block[0x80:0x90] = legacy_md5(encrypted)
    block[0x400:] = encrypted
    return bytes(block)


@pytest.fixture
def synthetic_serial() -> int:
    return SYNTHETIC_SERIAL


@pytest.fixture
def param_factory() -> Callable[..., bytes]:
    def factory(
        *,
        primary: bytes | None = None,
        backup: bytes | None = None,
        **block_options: int,
    ) -> bytes:
        default = make_sid_block(**block_options)
        primary_block = default if primary is None else primary
        backup_block = default if backup is None else backup
        image = bytearray(b"\xA5" * PARAM_SIZE)
        image[SID_OFFSETS[0]:SID_OFFSETS[0] + SID_SIZE] = primary_block
        image[SID_OFFSETS[1]:SID_OFFSETS[1] + SID_SIZE] = backup_block
        return bytes(image)

    return factory


@pytest.fixture
def pristine_param(param_factory: Callable[..., bytes]) -> bytes:
    return param_factory()
