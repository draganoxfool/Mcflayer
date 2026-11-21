# Mineflayer physics oracle

`tests/fixtures/physics_oracle.json` is generated with
[`prismarine-physics`](https://github.com/PrismarineJS/prismarine-physics), the engine Mineflayer
uses. It is the differential reference for the pure-Python `PhysicsEngine`.

```bash
cd tools/mineflayer_oracle
npm install
npm run generate
```

The fixture records 20 ticks for ten scripted traces on a flat 1.8.9 world. `node_modules/` is not
committed; only the generated JSON and this generator are.

Covered: walking, sprinting, sneaking, jumping, sprint-jumping, ice, slime, cobweb, water and lava.
Ladders, stairs and soul sand are exercised by `tests/test_physics.py`: ladders/stairs need
per-metadata shapes that the synthetic oracle world does not build, and prismarine-physics 1.8 does
not apply soul-sand slowdown because it only samples blocks intersecting the player hitbox. pyflayer
implements the vanilla `BlockSoulSand` supporting-block slowdown instead, so the divergence is
deliberate. Honey blocks do not exist in 1.8, so that gate is deferred to the first 1.15+ data set.
