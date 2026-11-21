from __future__ import annotations

import pytest

from pyflayer._internal.util import batched, ceil_log2, clamp, signed
from pyflayer.data.features import Features
from pyflayer.protocol.types.position import unpack_position


def test_util_helpers() -> None:
    assert ceil_log2(0) == 0
    assert ceil_log2(1) == 0
    assert ceil_log2(2) == 1
    assert ceil_log2(9) == 4
    assert signed(0xFFF, 12) == -1
    assert signed(0x7FF, 12) == 2047
    assert clamp(5, 0, 3) == 3
    assert list(batched(range(5), 2)) == [(0, 1), (2, 3), (4,)]


def test_position_layout_differs_between_18_and_modern() -> None:
    # One packed value: 1.14 reads y from the low 12 bits; 1.8 reads z from them.
    packed = (1 << 38) | (2 << 12) | 3
    modern = unpack_position(packed, packed_xzy=True)
    legacy = unpack_position(packed, packed_xzy=False)
    assert modern.x == 1 and modern.y == 3 and modern.z == 2
    assert legacy.x == 1 and legacy.y == 0 and legacy.z == 8195


def test_feature_flags_are_versioned() -> None:
    legacy = Features.for_version("1.8.9")
    modern = Features.for_version("1.20.4")
    assert legacy.protocol == 47 and modern.protocol == 765
    assert not legacy.position_packed_xzy and modern.position_packed_xzy
    assert not legacy.teleport_confirm and modern.teleport_confirm
    assert legacy.compression_supported and modern.compression_supported
    assert legacy.as_dict()["configuration_state"] is False
    assert modern.as_dict()["configuration_state"] is True
