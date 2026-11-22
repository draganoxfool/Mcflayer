"""Paletted block containers.

Three storage kinds are supported, matching the modern wire format and the 1.8 compatibility path:

* ``SINGLE`` — one value repeated across the whole container (zero per-entry storage).
* ``INDIRECT`` — a palette of values plus packed local indices.
* ``DIRECT`` — global values with no palette (used for 1.8 legacy state arrays).

Containers are immutable. :meth:`with_set` copies the index array (copy-on-write) so snapshots can
share sections safely (ADR-6). Decoding implements the 1.16+ non-spanning layout by default and the
pre-1.16 spanning layout when asked.

Examples:
    >>> box = PalettedContainer.single(0)
    >>> box = box.with_set(5, 16)
    >>> box.get(5), box.get(0)
    (16, 0)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

import numpy as np

from pyflayer.errors import OutOfWorldBounds
from pyflayer.protocol.buffer import PacketReader

__all__ = ["ContainerKind", "PalettedContainer"]


class ContainerKind(StrEnum):
    """Storage strategy of a container."""

    SINGLE = "single"
    INDIRECT = "indirect"
    DIRECT = "direct"


@dataclass(frozen=True, slots=True)
class PalettedContainer:
    """Immutable block/biome container.

    Attributes:
        kind: Storage strategy.
        bits_per_entry: Packed index width (0 for SINGLE).
        palette: Palette values for INDIRECT/SINGLE, ``None`` for DIRECT.
        indices: Index array (``uint8``/``uint16``), ``None`` for SINGLE.
        size: Number of entries (4096 for a section, 64 for a 4x4x4 biome cell).
    """

    kind: ContainerKind
    bits_per_entry: int
    palette: tuple[int, ...] | None
    indices: np.ndarray | None
    size: int = 4096

    def __post_init__(self) -> None:
        if self.indices is not None:
            self.indices.setflags(write=False)

    # ------------------------------------------------------------------ construction
    @classmethod
    def single(cls, value: int, *, size: int = 4096) -> PalettedContainer:
        """A uniform container holding ``value`` everywhere."""
        return cls(ContainerKind.SINGLE, 0, (int(value),), None, size)

    @classmethod
    def direct(cls, values: np.ndarray, *, bits: int = 16) -> PalettedContainer:
        """A DIRECT container over an existing array (the 1.8 legacy path)."""
        array = np.asarray(values)
        if array.ndim != 1:
            raise OutOfWorldBounds("container values must be one-dimensional")
        array = array.astype(np.uint16, copy=True)
        array.setflags(write=False)
        return cls(ContainerKind.DIRECT, max(1, bits), None, array, int(array.size))

    @classmethod
    def from_legacy(cls, states: np.ndarray) -> PalettedContainer:
        """Wrap a 1.8 ``uint16`` state array as a DIRECT container."""
        return cls.direct(states, bits=16)

    # ------------------------------------------------------------------ access
    def get(self, index: int) -> int:
        """Resolve the global value at ``index``."""
        self._check(index)
        if self.kind is ContainerKind.SINGLE:
            assert self.palette is not None
            return int(self.palette[0])
        assert self.indices is not None
        raw = int(self.indices[index])
        if self.kind is ContainerKind.DIRECT:
            return raw
        assert self.palette is not None
        return int(self.palette[raw])

    def with_set(self, index: int, value: int) -> PalettedContainer:
        """Return a copy with one entry changed (copy-on-write)."""
        self._check(index)
        value = int(value)
        if self.kind is ContainerKind.SINGLE:
            assert self.palette is not None
            if self.palette[0] == value:
                return self
            indices = np.zeros(self.size, dtype=np.uint8)
            indices[index] = 1
            indices.setflags(write=False)
            return PalettedContainer(
                ContainerKind.INDIRECT,
                1,
                (int(self.palette[0]), value),
                indices,
                self.size,
            )

        assert self.indices is not None
        if self.kind is ContainerKind.DIRECT:
            if int(self.indices[index]) == value:
                return self
            indices = self.indices.copy()
            indices[index] = value
            indices.setflags(write=False)
            return PalettedContainer(
                ContainerKind.DIRECT, self.bits_per_entry, None, indices, self.size
            )

        assert self.palette is not None
        current = self.get(index)
        if current == value:
            return self
        palette = list(self.palette)
        if value in palette:
            slot = palette.index(value)
        else:
            palette.append(value)
            slot = len(palette) - 1
        bits = max(1, _bits_for(len(palette)))
        dtype = np.uint8 if bits <= 8 else np.uint16
        indices = self.indices.astype(dtype, copy=True)
        indices[index] = slot
        indices.setflags(write=False)
        return PalettedContainer(ContainerKind.INDIRECT, bits, tuple(palette), indices, self.size)

    def with_sets(
        self, items: list[tuple[int, int]] | tuple[tuple[int, int], ...]
    ) -> PalettedContainer:
        """Apply several changes, copying at most once per call."""
        result = self
        for index, value in items:
            result = result.with_set(index, value)
        return result

    def to_array(self) -> np.ndarray:
        """Materialize the container into a ``uint16`` array."""
        if self.kind is ContainerKind.SINGLE:
            assert self.palette is not None
            return np.full(self.size, self.palette[0], dtype=np.uint16)
        assert self.indices is not None
        if self.kind is ContainerKind.DIRECT:
            return self.indices.astype(np.uint16, copy=True)
        assert self.palette is not None
        table = np.asarray(self.palette, dtype=np.uint16)
        result: np.ndarray = table[self.indices]
        return cast(np.ndarray, result.astype(np.uint16, copy=True))

    @property
    def non_air(self) -> int:
        """Number of non-zero (non-air) values."""
        if self.kind is ContainerKind.SINGLE:
            assert self.palette is not None
            return self.size if self.palette[0] else 0
        return int(np.count_nonzero(self.to_array()))

    def _check(self, index: int) -> None:
        if not 0 <= index < self.size:
            raise OutOfWorldBounds(
                "palette index outside the container", index=index, size=self.size
            )

    # ------------------------------------------------------------------ wire decoding
    @classmethod
    def decode(
        cls,
        reader: PacketReader,
        *,
        size: int = 4096,
        min_bits: int = 4,
        spanning: bool = False,
    ) -> PalettedContainer:
        """Decode a modern block/biome container.

        Args:
            reader: Reader positioned at the container.
            size: Number of entries (4096 for blocks, 64 for biomes).
            min_bits: Minimum index width (4 for blocks, 1 for biomes).
            spanning: Use the pre-1.16 layout where entries may straddle longs.

        Raises:
            MalformedPacket: On a truncated or inconsistent container.
        """
        bits = reader.read_u8()
        if bits == 0:
            return cls.single(reader.read_varint(), size=size)
        bits = max(bits, min_bits)
        palette_length = reader.read_varint()
        if palette_length < 0:
            from pyflayer.errors import MalformedPacket

            raise MalformedPacket("negative palette length", length=palette_length)
        palette = tuple(reader.read_varint() for _ in range(palette_length))
        data_length = reader.read_varint()
        if data_length < 0:
            from pyflayer.errors import MalformedPacket

            raise MalformedPacket("negative container data length", length=data_length)
        raw = reader.read_bytes(data_length * 8)
        longs = np.frombuffer(raw, dtype=">u8")
        indices = (
            _unpack_spanning(longs, size, bits)
            if spanning
            else _unpack_non_spanning(longs, size, bits)
        )
        indices.setflags(write=False)
        if not palette:
            return cls(ContainerKind.DIRECT, bits, None, indices, size)
        return cls(ContainerKind.INDIRECT, bits, palette, indices, size)


def _bits_for(values: int) -> int:
    return max(1, math.ceil(math.log2(max(2, values))))


def _unpack_non_spanning(longs: np.ndarray, size: int, bits: int) -> np.ndarray:
    per_long = 64 // bits
    mask = (1 << bits) - 1
    out = np.empty(size, dtype=np.uint16)
    for index in range(size):
        long_index = index // per_long
        if long_index >= len(longs):
            out[index] = 0
            continue
        shift = (index % per_long) * bits
        out[index] = (int(longs[long_index]) >> shift) & mask
    return out


def _unpack_spanning(longs: np.ndarray, size: int, bits: int) -> np.ndarray:
    out = np.empty(size, dtype=np.uint16)
    mask = (1 << bits) - 1
    for index in range(size):
        bit_index = index * bits
        long_index, shift = divmod(bit_index, 64)
        value = int(longs[long_index]) >> shift if long_index < len(longs) else 0
        if shift + bits > 64 and long_index + 1 < len(longs):
            value |= int(longs[long_index + 1]) << (64 - shift)
        out[index] = value & mask
    return out
