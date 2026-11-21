// Generate the physics differential fixture used by tests/test_physics_oracle.py.
//
// Usage:
//   npm install prismarine-physics@1.11.1 minecraft-data@3.75.0 vec3
//   node physics_traces.js > ../../tests/fixtures/physics_oracle.json
//
// The world is deliberately simple: a flat 16x16 stone floor and optional media layers. Each
// trace is 20 ticks with scripted controls. The output records position, velocity, on_ground and
// media flags after every tick. Minecraft 1.8.9 physics is selected through minecraft-data.

const mcData = require('minecraft-data')('1.8.9')
const { Physics } = require('prismarine-physics')
const { Vec3 } = require('vec3')

const FULL = [[0, 0, 0, 1, 1, 1]]
const blockId = (name) => mcData.blocksByName[name].id

function block(type, pos, shapes) {
  return {
    type,
    metadata: 0,
    position: new Vec3(pos.x, pos.y, pos.z),
    shapes,
    boundingBox: shapes.length ? 'block' : 'empty',
    _properties: {},
  }
}

function world(blockAt) {
  return { getBlock: (pos) => blockAt(pos) || block(0, pos, []) }
}

function flat({ floor = 'stone', layers = [] } = {}) {
  return (pos) => {
    for (const layer of layers) {
      if (pos.y >= layer.y0 && pos.y <= layer.y1) {
        return block(blockId(layer.name), pos, layer.shapes || [])
      }
    }
    if (pos.y <= 63) return block(blockId(floor), pos, FULL)
    return block(0, pos, [])
  }
}

function controls(extra = {}) {
  return {
    forward: false,
    back: false,
    left: false,
    right: false,
    jump: false,
    sprint: false,
    sneak: false,
    ...extra,
  }
}

function trace(name, blockAt, script) {
  const physics = Physics(mcData, world(blockAt))
  const player = {
    pos: new Vec3(8.5, 64, 8.5),
    vel: new Vec3(0, 0, 0),
    yaw: Math.PI, // faces +Z, matching pyflayer's yaw = 0
    pitch: 0,
    onGround: true,
    control: controls(),
    jumpTicks: 0,
    jumpQueued: false,
    jumpBoost: 0,
    slowFalling: 0,
    levitation: 0,
    depthStrider: 0,
    dolphinsGrace: 0,
    isInWater: false,
    isInLava: false,
    attributes: {},
    effects: {},
    food: 20,
    game: { gameMode: 'survival' },
    sprinting: false,
  }

  const samples = []
  for (let tick = 0; tick < 20; tick++) {
    Object.assign(player.control, script(tick))
    physics.simulatePlayer(player, world(blockAt))
    samples.push({
      pos: [player.pos.x, player.pos.y, player.pos.z].map((v) => +v.toFixed(9)),
      vel: [player.vel.x, player.vel.y, player.vel.z].map((v) => +v.toFixed(9)),
      onGround: !!player.onGround,
      inWater: !!player.isInWater,
      inLava: !!player.isInLava,
    })
  }
  return { name, trace: samples }
}

const forward = (extra = {}) => controls({ forward: true, ...extra })
const walk = () => forward()
const jumpOnFirstTick = (tick) => controls(tick === 0 ? { jump: true } : {})

const traces = [
  trace('walk_flat', flat(), walk),
  trace('sprint_flat', flat(), () => forward({ sprint: true })),
  trace('sneak_flat', flat(), () => forward({ sneak: true })),
  trace('jump', flat(), jumpOnFirstTick),
  trace('sprint_jump', flat(), (tick) => forward({ sprint: true, jump: tick === 0 })),
  trace('ice', flat({ floor: 'ice' }), walk),
  trace('slime', flat({ floor: 'slime' }), walk),
  trace('cobweb', flat({ layers: [{ name: 'web', y0: 64, y1: 65 }] }), walk),
  trace('water', flat({ layers: [{ name: 'water', y0: 64, y1: 65 }] }), walk),
  trace('lava', flat({ layers: [{ name: 'lava', y0: 64, y1: 65 }] }), walk),
]

process.stdout.write(
  JSON.stringify(
    {
      source: 'prismarine-physics 1.11.1 + minecraft-data 3.75.0',
      version: '1.8.9',
      generatedBy: 'tools/mineflayer_oracle/physics_traces.js',
      traces,
    },
    null,
    1,
  ) + '\n',
)
