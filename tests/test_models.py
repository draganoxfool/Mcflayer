from __future__ import annotations

from pyflayer.models.aabb import AABB
from pyflayer.models.enums import Face, GameMode
from pyflayer.models.items import ItemStack
from pyflayer.models.text import ChatComponent, chat_component_from_json
from pyflayer.models.vec3 import BlockPos, ChunkPos, SectionPos, Vec3


def test_vec3_math() -> None:
    a, b = Vec3(1, 2, 3), Vec3(0, 0, -3)
    assert a + b == Vec3(1.0, 2.0, 0.0)
    assert a - b == Vec3(1.0, 2.0, 6.0)
    assert a * 2 == Vec3(2.0, 4.0, 6.0)
    assert a.dot(b) == -9
    assert a.cross(b) == Vec3(-6.0, 3.0, 0.0)
    assert Vec3(3, 4, 0).length() == 5
    assert Vec3(0, 0, 0).normalize() == Vec3(0.0, 0.0, 0.0)
    assert Vec3(1.9, -0.1, -1.1).floored() == BlockPos(1, -1, -2)


def test_block_pos_chunk_conversion_with_negatives() -> None:
    assert BlockPos(-1, 0, 16).chunk == ChunkPos(-1, 1)
    assert BlockPos(-1, 0, 0).local_x() == 15
    assert BlockPos(0, -1, 0).section == SectionPos(0, -1, 0)
    assert BlockPos(5, 64, 7).with_y(70).to_vec3() == Vec3(5.5, 70.5, 7.5)


def test_aabb_intersection_and_contains() -> None:
    a = AABB(0, 0, 0, 1, 1, 1)
    b = AABB(0.5, 0.5, 0.5, 2, 2, 2)
    assert a.intersects(b)
    assert not a.intersects(AABB(1, 0, 0, 2, 1, 1))
    assert a.contains(Vec3(0.5, 0.5, 0.5))
    assert not a.contains(Vec3(2, 2, 2))
    assert a.translated(Vec3(1, 0, 0)).min_x == 1


def test_chat_component_flattening() -> None:
    comp = ChatComponent.parse({"text": "Hello ", "extra": [{"text": "world", "bold": True}]})
    assert comp.plain_text() == "Hello world"
    assert comp.extra[0].bold is True
    assert ChatComponent.parse([{"text": "a"}, {"text": "b"}]).plain_text() == "ab"


def test_chat_component_translate() -> None:
    comp = ChatComponent.parse(
        {"translate": "chat.type.text", "with": [{"text": "A"}, {"text": "hi"}]}
    )
    assert comp.plain_text(translate={"chat.type.text": "<{}> {}"}) == "<A> hi"


def test_chat_component_malformed_json_is_literal() -> None:
    assert chat_component_from_json("{not json").text == "{not json"
    assert chat_component_from_json(b'{"text":"ok"}').text == "ok"


def test_item_stack() -> None:
    stack = ItemStack(item_id=1, count=2, damage=3)
    assert not stack.empty
    assert stack.with_count(5).count == 5
    assert ItemStack().empty
    assert ItemStack(item_id=0, count=1).empty  # air
    assert ItemStack(item_id=-1, count=1).empty


def test_enums() -> None:
    assert GameMode.SURVIVAL == 0
    assert Face.EAST.offset == (1, 0, 0)
