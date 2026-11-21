from __future__ import annotations

import pytest

from pyflayer.data import Features, McData, default_data_dir, version_for_protocol, version_key
from pyflayer.errors import DataError, MissingRegistryEntry, UnsupportedVersion


@pytest.fixture(scope="module")
def mc() -> McData:
    return McData.load("1.8.9")


def test_reference_version(mc: McData) -> None:
    assert mc.version.protocol == 47
    assert mc.version.key == "1.8"
    assert mc.features.position_packed_xzy is False
    assert mc.features.network_nbt_nameless is False
    assert mc.features.block_state_ids is False


def test_registry_counts(mc: McData) -> None:
    assert len(mc.blocks) == 198
    assert len(mc.items) == 336
    assert len(mc.entities) == 58
    assert len(mc.biomes) == 61
    assert len(mc.effects) == 23
    assert len(mc.foods) == 28


def test_block_spot_checks(mc: McData) -> None:
    assert mc.blocks["stone"].id == 1
    assert mc.blocks["minecraft:stone"].id == 1
    assert mc.blocks[1].name == "stone"
    assert mc.blocks.state_id("stone") == 16
    block, metadata = mc.blocks.from_legacy_state_id(16)
    assert block.name == "stone"
    assert metadata == 0


def test_missing_entries(mc: McData) -> None:
    with pytest.raises(MissingRegistryEntry):
        mc.blocks["definitely_not_a_block"]
    assert mc.blocks.get("definitely_not_a_block") is None
    assert "stone" in mc.blocks
    assert 1 in mc.blocks


def test_shapes(mc: McData) -> None:
    assert mc.shapes.boxes_for("stone")[0].max_y == 1.0
    assert mc.shapes.boxes_for("air") == ()
    assert mc.collision_boxes(mc.blocks.state_id("stone"))[0].min_y == 0.0


def test_features_by_version() -> None:
    modern = Features.for_version("1.20.4")
    assert modern.protocol == 765
    assert modern.position_packed_xzy is True
    assert modern.network_nbt_nameless is True
    assert modern.configuration_state is True
    assert modern.supports("item_components") is False
    assert Features.for_version("1.20.6").supports("item_components") is True
    assert Features.for_version("1.21.5").supports("item_components") is True
    assert not Features.for_version("1.8.9").supports("does_not_exist")


def test_version_helpers() -> None:
    assert version_key("1.8.9") == "1.8"
    assert version_key(47) == "1.8"
    assert version_for_protocol(47) == "1.8"
    with pytest.raises(UnsupportedVersion):
        version_key(999999)


def test_unsupported_version() -> None:
    with pytest.raises(UnsupportedVersion):
        McData.load("1.20.4")  # not vendored in this repo


def test_default_data_dir_exists() -> None:
    assert default_data_dir().exists()


def test_bad_data_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYFLAYER_DATA_DIR", "/does/not/exist")
    with pytest.raises(DataError):
        default_data_dir()
