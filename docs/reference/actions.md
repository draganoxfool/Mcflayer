# `pyflayer.actions`

Scheduled actions and the single-writer control scheduler. This page documents the public classes and
functions; the [guide](../modules/actions.md) explains arbitration, preemption and the built-in
actions.

```python
from pyflayer.actions import Action, ActionScheduler, GoTo, Priority, Resource
```

## Primitives

::: pyflayer.actions.base.Resource

::: pyflayer.actions.base.Priority

::: pyflayer.actions.base.OnPreempt

::: pyflayer.actions.base.ActionState

::: pyflayer.actions.base.Action
    options:
      members: [run, on_preempted, checkpoint, restore]

::: pyflayer.actions.base.ControlHandle
    options:
      members: [set, look, jump, stop]

::: pyflayer.actions.base.Lease
    options:
      members: [priority, revoked, critical, look, jump, child]

::: pyflayer.actions.base.ActionHandle
    options:
      members: [done, cancelled, wait, cancel, lease, task, state, action, priority, resources]

## Scheduler

::: pyflayer.actions.scheduler.ActionScheduler
    options:
      members:
        - run
        - current
        - idle
        - active
        - cancel_all
        - set_barrier
        - release_barrier
        - metrics

## Built-in actions

::: pyflayer.actions.basic.Look

::: pyflayer.actions.basic.LookAt

::: pyflayer.actions.basic.GoTo

::: pyflayer.actions.basic.Dig

::: pyflayer.actions.basic.Place

::: pyflayer.actions.basic.Equip

::: pyflayer.actions.basic.Eat

::: pyflayer.actions.basic.Attack

::: pyflayer.actions.basic.face_position

## Facade

::: pyflayer.actions.facade.ActionFacade
    options:
      members:
        - run
        - look
        - look_at
        - goto
        - dig
        - place
        - equip
        - eat
        - attack
        - stop
        - scheduler

## Survival

::: pyflayer.actions.survival.SurvivalMonitor
    options:
      members: [start, stop, enabled, health, food, threshold, max_food]
