"""Protodef schema compiler.

``minecraft-data`` describes packets as JSON protodef schemas. Interpreting that JSON for every
packet would be far too slow, so this module compiles each type into a small codec object with
``read(reader, ctx)`` / ``write(writer, value, ctx)`` methods. Compilation is lazy (per packet type)
and cached.

Supported protodef types: ``varint``, ``varlong``, all fixed-width integers, ``f32``/``f64``,
``bool``, ``UUID``, ``pstring``/``string``, ``buffer``, ``restBuffer``, ``array`` (by count type or
count field), ``container``, ``switch``, ``option``, ``bitfield``, ``bitflags``, ``mapper``, ``void``,
``nbt``, ``optionalNbt``, ``anonymousNbt``, ``position`` and ``slot``.

``topBitSetTerminatedArray`` and entity-metadata types are deliberately left to
``protocol/native/`` codecs (M3); trying to compile them raises
:class:`~pyflayer.errors.UnsupportedType` rather than producing wrong bytes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from pyflayer.data.features import Features
from pyflayer.data.loader import McData, ProtocolSchema
from pyflayer.errors import MalformedPacket, UnsupportedType
from pyflayer.protocol.buffer import PacketReader, PacketWriter
from pyflayer.protocol.types.nbt import read_nbt, write_nbt
from pyflayer.protocol.types.slot import read_slot, write_slot

__all__ = [
    "Codec",
    "ProtocolCompiler",
    "PacketCodec",
    "Packet",
    "CompileReport",
]

Ctx = dict[str, Any]


class Codec(Protocol):
    """A compiled protodef type."""

    def read(self, reader: PacketReader, ctx: Ctx) -> Any: ...

    def write(self, writer: PacketWriter, value: Any, ctx: Ctx) -> None: ...


# --------------------------------------------------------------------------- primitives


class _FnCodec:
    __slots__ = ("_read", "_write")

    def __init__(self, read: Any, write: Any) -> None:
        self._read = read
        self._write = write

    def read(self, reader: PacketReader, ctx: Ctx) -> Any:
        return self._read(reader)

    def write(self, writer: PacketWriter, value: Any, ctx: Ctx) -> None:
        self._write(writer, value)


class _VoidCodec:
    __slots__ = ()

    def read(self, reader: PacketReader, ctx: Ctx) -> None:
        return None

    def write(self, writer: PacketWriter, value: Any, ctx: Ctx) -> None:
        return None


class _StringCodec:
    __slots__ = ("count", "max_chars")

    def __init__(self, count: Codec, max_chars: int = 32767) -> None:
        self.count = count
        self.max_chars = max_chars

    def read(self, reader: PacketReader, ctx: Ctx) -> str:
        length = int(self.count.read(reader, ctx))
        return reader.read_string_bytes(length, max_chars=self.max_chars)

    def write(self, writer: PacketWriter, value: Any, ctx: Ctx) -> None:
        if not isinstance(value, str):
            raise TypeError("string field must be str")
        length = len(value.encode("utf-8"))
        self.count.write(writer, length, ctx)
        writer.write_string_body(value, max_chars=self.max_chars)


class _BufferCodec:
    __slots__ = ("count", "rest")

    def __init__(self, count: Codec | None, rest: bool = False) -> None:
        self.count = count
        self.rest = rest

    def read(self, reader: PacketReader, ctx: Ctx) -> bytes:
        if self.rest:
            return reader.read_remaining()
        assert self.count is not None
        count = int(self.count.read(reader, ctx))
        if count < 0:
            raise MalformedPacket("negative buffer length", length=count)
        return reader.read_bytes(count)

    def write(self, writer: PacketWriter, value: Any, ctx: Ctx) -> None:
        data = bytes(value)
        if not self.rest:
            assert self.count is not None
            self.count.write(writer, len(data), ctx)
        writer.write_bytes(data)


class _ArrayCodec:
    __slots__ = ("element", "count", "count_field")

    def __init__(self, element: Codec, count: Codec | None, count_field: str | None) -> None:
        self.element = element
        self.count = count
        self.count_field = count_field

    def _length(self, reader: PacketReader, ctx: Ctx) -> int:
        if self.count_field is not None:
            value = ctx.get(self.count_field)
            if not isinstance(value, int):
                raise MalformedPacket("array count field is missing", field=self.count_field)
            return value
        assert self.count is not None
        return int(self.count.read(reader, ctx))

    def read(self, reader: PacketReader, ctx: Ctx) -> list[Any]:
        length = self._length(reader, ctx)
        if length < 0:
            raise MalformedPacket("negative array length", length=length)
        return [self.element.read(reader, ctx) for _ in range(length)]

    def write(self, writer: PacketWriter, value: Any, ctx: Ctx) -> None:
        items = list(value)  # type: ignore[call-overload]
        if self.count_field is None:
            assert self.count is not None
            self.count.write(writer, len(items), ctx)
        elif ctx.get(self.count_field) != len(items):
            ctx[self.count_field] = len(items)
        for item in items:
            self.element.write(writer, item, ctx)


class _ContainerCodec:
    __slots__ = ("fields",)

    def __init__(self, fields: list[tuple[str | None, Codec, bool]]) -> None:
        self.fields = fields

    def read(self, reader: PacketReader, ctx: Ctx) -> dict[str, Any]:
        local: Ctx = dict(ctx)
        result: dict[str, Any] = {}
        for name, codec, anon in self.fields:
            value = codec.read(reader, local)
            if anon:
                if isinstance(value, dict):
                    result.update(value)
                    local.update(value)
                else:
                    result[f"__anon_{len(result)}"] = value
            else:
                assert name is not None
                result[name] = value
                local[name] = value
        return result

    def write(self, writer: PacketWriter, value: Any, ctx: Ctx) -> None:
        if not isinstance(value, dict):
            raise TypeError("container value must be a dict")
        local: Ctx = dict(ctx)
        for name, codec, anon in self.fields:
            if anon:
                codec.write(writer, value, local)
                continue
            assert name is not None
            field_value = value.get(name)
            codec.write(writer, field_value, local)
            local[name] = field_value


class _SwitchCodec:
    __slots__ = ("compare_to", "fields", "default")

    def __init__(self, compare_to: str, fields: dict[str, Codec], default: Codec | None) -> None:
        self.compare_to = compare_to
        self.fields = fields
        self.default = default

    def _select(self, ctx: Ctx) -> Codec:
        key = self.compare_to
        while key.startswith("../"):  # parent-context references, e.g. "../action"
            key = key[3:]
        if key.startswith("$"):
            key = key[1:]
        value = ctx.get(key)
        codec = self.fields.get(str(value))
        if codec is None:
            codec = self.fields.get(str(value).lower())
        if codec is None:
            codec = self.default
        if codec is None:
            raise MalformedPacket(
                "no switch branch",
                compare_to=self.compare_to,
                value=value,
            )
        return codec

    def read(self, reader: PacketReader, ctx: Ctx) -> Any:
        return self._select(ctx).read(reader, ctx)

    def write(self, writer: PacketWriter, value: Any, ctx: Ctx) -> None:
        self._select(ctx).write(writer, value, ctx)


class _OptionCodec:
    __slots__ = ("inner",)

    def __init__(self, inner: Codec) -> None:
        self.inner = inner

    def read(self, reader: PacketReader, ctx: Ctx) -> Any:
        return self.inner.read(reader, ctx) if reader.read_bool() else None

    def write(self, writer: PacketWriter, value: Any, ctx: Ctx) -> None:
        writer.write_bool(value is not None)
        if value is not None:
            self.inner.write(writer, value, ctx)


def _read_packed_bits(reader: PacketReader, bits: int) -> int:
    if bits <= 0:
        return 0
    size = (bits + 7) // 8
    raw = reader.read_bytes(size)
    return int.from_bytes(raw, "big") >> (size * 8 - bits)


def _write_packed_bits(writer: PacketWriter, value: int, bits: int) -> None:
    size = (bits + 7) // 8
    if bits <= 0:
        return
    padded = value << (size * 8 - bits)
    writer.write_bytes(padded.to_bytes(size, "big"))


class _BitfieldCodec:
    __slots__ = ("fields", "total_bits")

    def __init__(self, fields: list[dict[str, Any]]) -> None:
        self.fields = fields
        self.total_bits = sum(int(field["size"]) for field in fields)

    def read(self, reader: PacketReader, ctx: Ctx) -> dict[str, int]:
        packed = _read_packed_bits(reader, self.total_bits)
        result: dict[str, int] = {}
        remaining = self.total_bits
        for entry in self.fields:
            size = int(entry["size"])
            remaining -= size
            value = (packed >> remaining) & ((1 << size) - 1)
            if entry.get("signed", False) and value & (1 << (size - 1)):
                value -= 1 << size
            result[str(entry["name"])] = value
        return result

    def write(self, writer: PacketWriter, value: Any, ctx: Ctx) -> None:
        if not isinstance(value, dict):
            raise TypeError("bitfield value must be a dict")
        packed = 0
        remaining = self.total_bits
        for entry in self.fields:
            size = int(entry["size"])
            remaining -= size
            raw = int(value.get(str(entry["name"]), 0)) & ((1 << size) - 1)
            packed |= raw << remaining
        _write_packed_bits(writer, packed, self.total_bits)


class _BitflagsCodec:
    __slots__ = ("flags", "total_bits")

    def __init__(self, flags: list[dict[str, Any]]) -> None:
        self.flags = flags
        self.total_bits = sum(int(flag["size"]) for flag in flags)

    def read(self, reader: PacketReader, ctx: Ctx) -> dict[str, bool]:
        packed = _read_packed_bits(reader, self.total_bits)
        result: dict[str, bool] = {}
        remaining = self.total_bits
        for flag in self.flags:
            size = int(flag["size"])
            remaining -= size
            result[str(flag["name"])] = bool((packed >> remaining) & ((1 << size) - 1))
        return result

    def write(self, writer: PacketWriter, value: Any, ctx: Ctx) -> None:
        if not isinstance(value, dict):
            raise TypeError("bitflags value must be a dict")
        packed = 0
        remaining = self.total_bits
        for flag in self.flags:
            size = int(flag["size"])
            remaining -= size
            if value.get(str(flag["name"])):
                packed |= ((1 << size) - 1) << remaining
        _write_packed_bits(writer, packed, self.total_bits)


class _MapperCodec:
    __slots__ = ("inner", "to_name", "to_id", "numeric")

    def __init__(self, inner: Codec, mappings: dict[str, str]) -> None:
        self.inner = inner
        self.to_name: dict[int, str] = {}
        self.to_id: dict[str, int] = {}
        self.numeric: dict[str, int] = {}
        for raw_key, name in mappings.items():
            number = _parse_int_key(raw_key)
            self.to_name[number] = name
            self.to_id.setdefault(name, number)
            self.numeric[name] = number

    def read(self, reader: PacketReader, ctx: Ctx) -> Any:
        number = int(self.inner.read(reader, ctx))
        return self.to_name.get(number, number)

    def write(self, writer: PacketWriter, value: Any, ctx: Ctx) -> None:
        if isinstance(value, str):
            if value not in self.to_id:
                raise MalformedPacket("mapper value not in mappings", value=value)
            self.inner.write(writer, self.to_id[value], ctx)
        else:
            self.inner.write(writer, int(value), ctx)


def _parse_int_key(key: str) -> int:
    text = str(key).strip()
    try:
        return int(text, 0)
    except ValueError:
        return int(text, 10)


class _NbtCodec:
    __slots__ = ("named", "optional")

    def __init__(self, named: bool, optional: bool = False) -> None:
        self.named = named
        self.optional = optional

    def read(self, reader: PacketReader, ctx: Ctx) -> Any:
        if self.optional and not reader.read_bool():
            return None
        value = read_nbt(reader, named=self.named)
        return value.value if hasattr(value, "value") else value

    def write(self, writer: PacketWriter, value: Any, ctx: Ctx) -> None:
        if self.optional:
            writer.write_bool(value is not None)
            if value is None:
                return
        writer.write_bytes(write_nbt(value, named=self.named))


class _SlotCodec:
    __slots__ = ("features",)

    def __init__(self, features: Features) -> None:
        self.features = features

    def read(self, reader: PacketReader, ctx: Ctx) -> Any:
        return read_slot(reader, self.features)

    def write(self, writer: PacketWriter, value: Any, ctx: Ctx) -> None:
        write_slot(value, writer, self.features)


# --------------------------------------------------------------------------- compiler


@dataclass(slots=True)
class CompileReport:
    """Result of compiling every packet in a state/direction."""

    state: str
    direction: str
    compiled: list[str] = field(default_factory=list)
    unsupported: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """True when every packet compiled."""
        return not self.unsupported


class ProtocolCompiler:
    """Compile a :class:`ProtocolSchema` into cached codecs."""

    def __init__(
        self,
        protocol: ProtocolSchema,
        features: Features,
        *,
        native_packets: dict[tuple[str, str, str], Codec] | None = None,
    ) -> None:
        self.protocol = protocol
        self.features = features
        self.native_packets = dict(native_packets or {})
        self._cache: dict[tuple[str, str, str], Codec] = {}
        self._compiling: set[tuple[str, str, str]] = set()

    # ------------------------------------------------------------------ public
    def compile_type(self, spec: Any, state: str, direction: str) -> Codec:
        """Compile an inline type specification."""
        return self._compile(spec, state, direction)

    def packet_codec(self, state: str, direction: str, name: str) -> Codec:
        """Compile (and cache) the parameter container for one packet."""
        override = self.native_packets.get((state, direction, name))
        if override is not None:
            return override
        type_name = f"packet_{name}"
        types = self.protocol.types(state, direction)
        if type_name not in types:
            raise UnsupportedType(
                f"packet {name!r} has no {type_name} type",
                type_name=type_name,
                state=state,
                direction=direction,
            )
        return self._compile_named(type_name, state, direction)

    def compile_state(self, state: str, direction: str) -> CompileReport:
        """Compile every packet type in one state/direction."""
        report = CompileReport(state, direction)
        for name in sorted(packet_names(self.protocol, state, direction)):
            try:
                self.packet_codec(state, direction, name)
            except UnsupportedType as exc:
                report.unsupported[name] = str(exc)
            except Exception as exc:  # noqa: BLE001 - report, do not abort the sweep
                report.unsupported[name] = f"{type(exc).__name__}: {exc}"
            else:
                report.compiled.append(name)
        return report

    # ------------------------------------------------------------------ internals
    def _compile(self, spec: Any, state: str, direction: str) -> Codec:
        if isinstance(spec, str):
            return self._compile_named(spec, state, direction)
        if isinstance(spec, (list, tuple)) and spec:
            name = spec[0]
            params = spec[1] if len(spec) > 1 else None
            if isinstance(name, str):
                return self._compile_native(name, params, state, direction)
            # ["container", [...]] etc. are strings; a nested list head is unusual.
            raise UnsupportedType("unsupported protodef type head", type_name=str(name))
        raise UnsupportedType("unsupported protodef type", type_name=repr(spec))

    def _compile_named(self, name: str, state: str, direction: str) -> Codec:
        key = (state, direction, name)
        if key in self._cache:
            return self._cache[key]
        if name == "slot":
            # The native slot codec produces immutable ItemStack values; the JSON slot container
            # would expose raw blockId/itemCount dicts to every caller of the registry.
            codec = _SlotCodec(self.features)
            self._cache[key] = codec
            return codec
        local = self.protocol.types(state, direction)
        if name in local:
            spec = local[name]
            if key in self._compiling:
                raise UnsupportedType("recursive protodef type", type_name=name)
            self._compiling.add(key)
            try:
                codec = self._compile(spec, state, direction)
            finally:
                self._compiling.discard(key)
            self._cache[key] = codec
            return codec
        if name in self.protocol.global_types:
            spec = self.protocol.global_types[name]
            if not isinstance(spec, str) or spec != "native":
                return self._compile(spec, state, direction)
        return self._compile_native(name, None, state, direction)

    def _compile_native(
        self, name: str, params: Any, state: str, direction: str
    ) -> Codec:
        p: dict[str, Any] = params if isinstance(params, dict) else {}

        def count_codec() -> Codec:
            count_type = p.get("countType", "varint")
            return self._compile(count_type, state, direction)

        if name in {"u8", "i8", "u16", "i16", "u32", "i32", "u64", "i64", "f32", "f64", "bool"}:
            return _FnCodec(
                lambda reader, n=name: getattr(reader, f"read_{n}")(),
                lambda writer, value, n=name: getattr(writer, f"write_{n}")(value),
            )
        if name == "varint":
            return _FnCodec(lambda reader: reader.read_varint(), lambda writer, value: writer.write_varint(int(value)))
        if name == "varlong":
            return _FnCodec(lambda reader: reader.read_varlong(), lambda writer, value: writer.write_varlong(int(value)))
        if name == "void":
            return _VoidCodec()
        if name == "UUID":
            return _FnCodec(lambda reader: reader.read_uuid(), lambda writer, value: writer.write_uuid(value))
        if name in {"pstring", "string"}:
            max_chars = int(p.get("maxLength", 32767))
            return _StringCodec(count_codec(), max_chars)
        if name == "buffer":
            return _BufferCodec(count_codec(), False)
        if name == "restBuffer":
            return _BufferCodec(None, True)
        if name == "array":
            if "countType" in p:
                count = count_codec()
                field_name = None
            elif "count" in p:
                count_spec = p["count"]
                if isinstance(count_spec, int):
                    fixed = count_spec

                    def _fixed_read(reader: PacketReader, _n: int = fixed) -> int:
                        return _n

                    count = _FnCodec(_fixed_read, lambda writer, value: None)
                    field_name = None
                elif isinstance(count_spec, str) and not _looks_like_type(count_spec):
                    count = None
                    field_name = count_spec
                else:
                    count = self._compile(count_spec, state, direction)
                    field_name = None
            else:
                count = self._compile("varint", state, direction)
                field_name = None
            element = self._compile(p.get("type", "u8"), state, direction)
            return _ArrayCodec(element, count, field_name)
        if name == "container":
            fields: list[tuple[str | None, Codec, bool]] = []
            entries = params if isinstance(params, list) else []
            for entry in entries:
                field_name = entry.get("name")
                anon = bool(entry.get("anon", False))
                fields.append((field_name, self._compile(entry["type"], state, direction), anon))
            return _ContainerCodec(fields)
        if name == "switch":
            compare_to = str(p.get("compareTo", ""))
            fields_raw = p.get("fields", {})
            fields_map: dict[str, Codec] = {}
            if isinstance(fields_raw, dict):
                for key, spec in fields_raw.items():
                    fields_map[str(key)] = self._compile(spec, state, direction)
            default = p.get("default")
            return _SwitchCodec(
                compare_to,
                fields_map,
                self._compile(default, state, direction) if default is not None else None,
            )
        if name == "option":
            # ``option`` params are either a bare type name (``["option", "string"]``) or a
            # mapping (``["option", {"type": "string"}]``). Treating the bare string as an empty
            # mapping silently compiled ``option(void)``, which consumed only the presence flag and
            # shifted every following field.
            if isinstance(params, dict):
                inner_spec = params.get("type", "void")
            elif params is None:
                inner_spec = "void"
            else:
                inner_spec = params
            return _OptionCodec(self._compile(inner_spec, state, direction))
        if name == "bitfield":
            return _BitfieldCodec(list(params or []))
        if name == "bitflags":
            return _BitflagsCodec(list(params or []))
        if name == "mapper":
            inner = self._compile(p.get("type", "varint"), state, direction)
            mappings = p.get("mappings", {})
            return _MapperCodec(inner, dict(mappings) if isinstance(mappings, dict) else {})
        if name in {"nbt", "optionalNbt", "anonymousNbt"}:
            return _NbtCodec(name != "anonymousNbt", optional=name == "optionalNbt")
        if name == "position":
            packed_xzy = self.features.position_packed_xzy
            return _FnCodec(
                lambda reader: reader.read_position(packed_xzy=packed_xzy),
                lambda writer, value: writer.write_position(value, packed_xzy=packed_xzy),
            )
        if name == "slot":
            return _SlotCodec(self.features)
        if name == "entityMetadataLoop":
            from pyflayer.protocol.native.entity_metadata import EntityMetadataLoopCodec

            return EntityMetadataLoopCodec()
        raise UnsupportedType(
            f"protodef type {name!r} is not implemented",
            type_name=name,
            state=state,
            direction=direction,
            hint="implement it under protocol/native/",
        )


def _looks_like_type(text: str) -> bool:
    return text in {
        "varint",
        "varlong",
        "u8",
        "i8",
        "u16",
        "i16",
        "u32",
        "i32",
        "u64",
        "i64",
        "f32",
        "f64",
    }


def packet_names(protocol: ProtocolSchema, state: str, direction: str) -> list[str]:
    """Names of packets declared for a state/direction."""
    names: list[str] = []
    for type_name in protocol.types(state, direction):
        if type_name.startswith("packet_") and type_name != "packet":
            names.append(type_name[len("packet_") :])
    return names


def packet_mappings(protocol: ProtocolSchema, state: str, direction: str) -> dict[int, str]:
    """Extract ``id -> name`` from the top-level ``packet`` mapper."""
    spec = protocol.packet_type(state, direction)
    if not isinstance(spec, (list, tuple)) or len(spec) < 2:
        return {}
    fields = spec[1]
    if not isinstance(fields, list):
        return {}
    for entry in fields:
        if not isinstance(entry, dict) or entry.get("name") != "name":
            continue
        type_spec = entry.get("type")
        if not isinstance(type_spec, (list, tuple)) or len(type_spec) < 2:
            continue
        params = type_spec[1]
        if not isinstance(params, dict):
            continue
        mappings = params.get("mappings")
        if isinstance(mappings, dict):
            return {_parse_int_key(key): str(value) for key, value in mappings.items()}
    return {}


@dataclass(frozen=True, slots=True)
class Packet:
    """A decoded packet: protocol-level, no game semantics (ADR-3)."""

    name: str
    fields: dict[str, Any]
    state: str
    direction: str
    raw_len: int = 0


class PacketCodec:
    """Binds a state/direction to its packet ids and lazily compiled codecs."""

    __slots__ = ("state", "direction", "compiler", "ids", "names")

    def __init__(self, state: str, direction: str, compiler: ProtocolCompiler, ids: dict[int, str]) -> None:
        self.state = state
        self.direction = direction
        self.compiler = compiler
        self.ids = ids
        self.names = {name: packet_id for packet_id, name in ids.items()}

    @classmethod
    def build(cls, mc: McData, compiler: ProtocolCompiler, state: str, direction: str) -> PacketCodec:
        """Build from data, extracting the packet-id mapper."""
        del mc  # kept for a stable call signature
        return cls(state, direction, compiler, packet_mappings(compiler.protocol, state, direction))

    def decode(self, payload: bytes, *, strict: bool = True) -> Packet:
        """Decode a full payload (packet id + fields)."""
        from pyflayer.errors import UnknownPacket
        from pyflayer.protocol.varint import decode_varint

        packet_id, consumed = decode_varint(payload)
        name = self.ids.get(packet_id)
        if name is None:
            raise UnknownPacket(
                f"unknown packet id 0x{packet_id:02x}",
                packet_id=packet_id,
                raw=payload[consumed:],
                state=self.state,
                direction=self.direction,
            )
        reader = PacketReader(payload[consumed:], features=self.compiler.features, packet_name=name)
        codec = self.compiler.packet_codec(self.state, self.direction, name)
        fields = codec.read(reader, {})
        reader.ensure_finished(strict=strict)
        if not isinstance(fields, dict):
            raise MalformedPacket("packet fields must decode to a dict", packet=name)
        return Packet(name, fields, self.state, self.direction, raw_len=len(payload))

    def encode(self, name: str, fields: dict[str, Any]) -> bytes:
        """Encode a packet by name. Returns the full payload including the id."""
        from pyflayer.protocol.varint import encode_varint

        packet_id = self.names.get(name)
        if packet_id is None:
            from pyflayer.errors import UnsupportedType

            raise UnsupportedType(f"unknown packet name {name!r}", type_name=name)
        writer = PacketWriter(features=self.compiler.features)
        writer.write_bytes(encode_varint(packet_id))
        codec = self.compiler.packet_codec(self.state, self.direction, name)
        codec.write(writer, fields, {})
        return writer.to_bytes()

    def __contains__(self, name: object) -> bool:
        return name in self.names
