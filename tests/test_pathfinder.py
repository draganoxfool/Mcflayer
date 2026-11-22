from __future__ import annotations

import pytest

from pyflayer.data import McData
from pyflayer.errors import NoPath
from pyflayer.models.vec3 import BlockPos, ChunkPos
from pyflayer.pathfinder import (
    GoalBlock,
    GoalCompositeAll,
    GoalCompositeAny,
    GoalInvert,
    GoalNear,
    GoalXZ,
    PathPlanner,
    search,
)

MC = McData.load("1.8.9")
STONE = 16


class FlatWorld:
    """Flat stone floor at y=63, air above, every chunk loaded."""

    min_y = 0
    height = 256

    def is_loaded(self, pos: ChunkPos) -> bool:
        return True

    def block_state_id(self, pos: BlockPos) -> int:
        return STONE if pos.y < 64 else 0

    def snapshot(self) -> FlatWorld:
        return self


class EmptyWorld(FlatWorld):
    def is_loaded(self, pos: ChunkPos) -> bool:
        return False


def test_goals_accept_their_targets() -> None:
    assert GoalBlock(BlockPos(1, 2, 3)).is_end(BlockPos(1, 2, 3))
    assert not GoalBlock(BlockPos(1, 2, 3)).is_end(BlockPos(1, 2, 4))
    assert GoalNear(BlockPos(0, 0, 0), 2).is_end(BlockPos(2, 0, 0))
    assert not GoalNear(BlockPos(0, 0, 0), 2).is_end(BlockPos(3, 0, 0))
    assert GoalXZ(3, -4).is_end(BlockPos(3, 90, -4))
    assert GoalInvert(GoalBlock(BlockPos(0, 0, 0))).is_end(BlockPos(1, 0, 0))
    assert GoalCompositeAny([GoalBlock(BlockPos(0, 0, 0)), GoalXZ(4, 4)]).is_end(
        BlockPos(4, 20, 4)
    )
    assert GoalCompositeAll([GoalXZ(4, 4), GoalNear(BlockPos(4, 20, 4), 1)]).is_end(
        BlockPos(4, 20, 4)
    )
    assert GoalBlock(BlockPos(3, 64, 0)).heuristic(BlockPos(0, 64, 0)) == 3


def test_search_finds_a_straight_path() -> None:
    result = search(
        FlatWorld(), MC, BlockPos(0, 64, 0), GoalBlock(BlockPos(3, 64, 0))
    )
    assert result.complete
    assert result.path[0] == BlockPos(0, 64, 0)
    assert result.path[-1] == BlockPos(3, 64, 0)
    assert result.expanded >= 3
    assert result.cost > 0


def test_search_returns_a_partial_path_on_budget_exhaustion() -> None:
    result = search(
        FlatWorld(),
        MC,
        BlockPos(0, 64, 0),
        GoalBlock(BlockPos(10, 64, 0)),
        max_nodes=2,
    )
    assert not result.complete
    assert result.path[0] == BlockPos(0, 64, 0)
    assert result.expanded == 2


def test_planner_raises_no_path_with_partial_path() -> None:
    planner = PathPlanner(EmptyWorld(), MC)
    with pytest.raises(NoPath) as info:
        planner.plan_sync(BlockPos(0, 64, 0), GoalBlock(BlockPos(1, 64, 0)))
    partial = info.value.fields["partial"]
    assert partial is not None and not partial.complete
    assert partial.points == (BlockPos(0, 64, 0),)


def test_planner_sync_and_async_agree() -> None:
    planner = PathPlanner(FlatWorld(), MC)
    sync_path = planner.plan_sync(BlockPos(0, 64, 0), GoalBlock(BlockPos(2, 64, 0)))
    assert sync_path.complete
    assert sync_path.end == BlockPos(2, 64, 0)

    async def run() -> None:
        path = await planner.plan(
            BlockPos(0, 64, 0), GoalBlock(BlockPos(2, 64, 0))
        )
        assert path.points == sync_path.points

    import asyncio

    asyncio.run(run())


def test_search_rejects_zero_budget() -> None:
    with pytest.raises(ValueError):
        search(FlatWorld(), MC, BlockPos(0, 64, 0), GoalBlock(BlockPos(1, 64, 0)), max_nodes=0)


def test_search_does_not_cut_corners() -> None:
    # A wall between the start and the goal forces the path around the corner.
    class WallWorld(FlatWorld):
        def block_state_id(self, pos: BlockPos) -> int:
            if pos.x == 1 and pos.z == 0 and 64 <= pos.y < 66:
                return STONE
            return super().block_state_id(pos)

    result = search(
        WallWorld(), MC, BlockPos(0, 64, 0), GoalBlock(BlockPos(2, 64, 0))
    )
    assert result.complete
    assert BlockPos(1, 64, 0) not in result.path
    assert len(result.path) > 3
