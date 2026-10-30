import { describe, expect, it } from 'vitest'
import { applyMove, dropSlotToPosition, neighborTarget, tasksInColumn } from './moveLogic'

type T = { id: string; column_id: string; position: number }

const t = (id: string, column_id: string, position: number): T => ({ id, column_id, position })

const BOARD: T[] = [
  t('a0', 'A', 0),
  t('a1', 'A', 1),
  t('a2', 'A', 2),
  t('a3', 'A', 3),
  t('b0', 'B', 0),
  t('b1', 'B', 1),
]

const order = (tasks: T[], column: string) => tasksInColumn(tasks, column).map((x) => x.id)

function expectDense(tasks: T[]) {
  for (const column of new Set(tasks.map((x) => x.column_id))) {
    expect(tasksInColumn(tasks, column).map((x) => x.position)).toEqual(
      tasksInColumn(tasks, column).map((_, i) => i),
    )
  }
}

interface Case {
  name: string
  taskId: string
  column: string
  requested: number
  expectA: string[]
  expectB: string[]
  expectC?: string[]
  position: number
  changed: boolean
}

const CASES: Case[] = [
  // within a column
  {
    name: 'down accounts for the removed slot',
    taskId: 'a0',
    column: 'A',
    requested: 2,
    position: 2,
    changed: true,
    expectA: ['a1', 'a2', 'a0', 'a3'],
    expectB: ['b0', 'b1'],
  },
  {
    name: 'down to the very bottom',
    taskId: 'a1',
    column: 'A',
    requested: 3,
    position: 3,
    changed: true,
    expectA: ['a0', 'a2', 'a3', 'a1'],
    expectB: ['b0', 'b1'],
  },
  {
    name: 'up',
    taskId: 'a3',
    column: 'A',
    requested: 1,
    position: 1,
    changed: true,
    expectA: ['a0', 'a3', 'a1', 'a2'],
    expectB: ['b0', 'b1'],
  },
  {
    name: 'up to the top',
    taskId: 'a2',
    column: 'A',
    requested: 0,
    position: 0,
    changed: true,
    expectA: ['a2', 'a0', 'a1', 'a3'],
    expectB: ['b0', 'b1'],
  },
  {
    name: 'same slot is a no-op',
    taskId: 'a1',
    column: 'A',
    requested: 1,
    position: 1,
    changed: false,
    expectA: ['a0', 'a1', 'a2', 'a3'],
    expectB: ['b0', 'b1'],
  },
  {
    name: 'past the end clamps to last',
    taskId: 'a0',
    column: 'A',
    requested: 99,
    position: 3,
    changed: true,
    expectA: ['a1', 'a2', 'a3', 'a0'],
    expectB: ['b0', 'b1'],
  },
  {
    name: 'last task moved past the end stays put',
    taskId: 'a3',
    column: 'A',
    requested: 50,
    position: 3,
    changed: false,
    expectA: ['a0', 'a1', 'a2', 'a3'],
    expectB: ['b0', 'b1'],
  },
  {
    name: 'negative clamps to the top',
    taskId: 'a2',
    column: 'A',
    requested: -4,
    position: 0,
    changed: true,
    expectA: ['a2', 'a0', 'a1', 'a3'],
    expectB: ['b0', 'b1'],
  },
  // across columns
  {
    name: 'cross-column insert at top',
    taskId: 'a1',
    column: 'B',
    requested: 0,
    position: 0,
    changed: true,
    expectA: ['a0', 'a2', 'a3'],
    expectB: ['a1', 'b0', 'b1'],
  },
  {
    name: 'cross-column insert in the middle',
    taskId: 'a1',
    column: 'B',
    requested: 1,
    position: 1,
    changed: true,
    expectA: ['a0', 'a2', 'a3'],
    expectB: ['b0', 'a1', 'b1'],
  },
  {
    name: 'cross-column insert at the end',
    taskId: 'a0',
    column: 'B',
    requested: 2,
    position: 2,
    changed: true,
    expectA: ['a1', 'a2', 'a3'],
    expectB: ['b0', 'b1', 'a0'],
  },
  {
    name: 'cross-column past the end clamps',
    taskId: 'a3',
    column: 'B',
    requested: 40,
    position: 2,
    changed: true,
    expectA: ['a0', 'a1', 'a2'],
    expectB: ['b0', 'b1', 'a3'],
  },
  {
    name: 'into an empty column',
    taskId: 'b1',
    column: 'C',
    requested: 0,
    position: 0,
    changed: true,
    expectA: ['a0', 'a1', 'a2', 'a3'],
    expectB: ['b0'],
    expectC: ['b1'],
  },
  {
    name: 'into an empty column with a too-large position',
    taskId: 'a0',
    column: 'C',
    requested: 7,
    position: 0,
    changed: true,
    expectA: ['a1', 'a2', 'a3'],
    expectB: ['b0', 'b1'],
    expectC: ['a0'],
  },
]

describe('applyMove', () => {
  it.each(CASES)('$name', (c) => {
    const result = applyMove(BOARD, c.taskId, c.column, c.requested)
    expect(result).not.toBeNull()
    expect(result?.position).toBe(c.position)
    expect(result?.columnId).toBe(c.column)
    expect(result?.changed).toBe(c.changed)
    const tasks = result?.tasks ?? []
    expect(order(tasks, 'A')).toEqual(c.expectA)
    expect(order(tasks, 'B')).toEqual(c.expectB)
    expect(order(tasks, 'C')).toEqual(c.expectC ?? [])
    expect(tasks).toHaveLength(BOARD.length)
    expectDense(tasks)
  })

  it('does not mutate its input and returns null for an unknown task', () => {
    const snapshot = JSON.stringify(BOARD)
    applyMove(BOARD, 'a0', 'B', 1)
    expect(JSON.stringify(BOARD)).toBe(snapshot)
    expect(applyMove(BOARD, 'missing', 'B', 0)).toBeNull()
  })

  it('renumbers densely even if the input positions had gaps', () => {
    const gappy = [t('x', 'A', 0), t('y', 'A', 5), t('z', 'A', 9)]
    expectDense(applyMove(gappy, 'z', 'A', 0)?.tasks ?? [])
  })
})

describe('dropSlotToPosition', () => {
  it.each([
    ['dropping just below itself in the same column is a no-op slot', 'a1', 'A', 2, 1],
    ['dropping lower in the same column shifts by one', 'a0', 'A', 3, 2],
    ['dropping higher in the same column is unchanged', 'a3', 'A', 1, 1],
    ['dropping at the very end of the same column', 'a0', 'A', 4, 3],
    ['another column uses the slot as is', 'a0', 'B', 1, 1],
  ])('%s', (_name, id, column, slot, expected) => {
    expect(dropSlotToPosition(BOARD, id as string, column as string, slot as number)).toBe(expected)
  })
})

describe('neighborTarget (keyboard alternative)', () => {
  const columns = ['A', 'B', 'C']
  it.each([
    ['up', 'a2', 'up', { columnId: 'A', position: 1 }],
    ['up at the top', 'a0', 'up', null],
    ['down', 'a1', 'down', { columnId: 'A', position: 2 }],
    ['down at the bottom', 'a3', 'down', null],
    ['right keeps the row', 'a1', 'right', { columnId: 'B', position: 1 }],
    ['right from the last column', 'b0', 'right', { columnId: 'C', position: 0 }],
    ['left from the first column', 'a0', 'left', null],
    ['left', 'b1', 'left', { columnId: 'A', position: 1 }],
  ] as const)('%s', (_name, id, direction, expected) => {
    expect(neighborTarget(BOARD, columns, id, direction)).toEqual(expected)
  })

  it('right from the last column is impossible', () => {
    expect(neighborTarget([t('c0', 'C', 0)], columns, 'c0', 'right')).toBeNull()
  })
})
