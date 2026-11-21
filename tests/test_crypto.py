from __future__ import annotations

import pytest

from pyflayer.protocol.crypto import CipherPair


def test_cfb8_roundtrip_streaming() -> None:
    secret = bytes(range(16))
    enc, dec = CipherPair(secret), CipherPair(secret)
    for chunk in (b"hello ", b"minecraft ", b"world"):
        assert dec.decrypt(enc.encrypt(chunk)) == chunk


def test_independent_directions() -> None:
    secret = b"\x01" * 16
    enc, dec = CipherPair(secret), CipherPair(secret)
    first = enc.encrypt(b"abc")
    second = enc.encrypt(b"def")
    assert dec.decrypt(first + second) == b"abcdef"


def test_key_length_validated() -> None:
    with pytest.raises(ValueError):
        CipherPair(b"short")
