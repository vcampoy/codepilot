import { describe, expect, it } from 'vitest'
import { chunkSelection, selectionState, toggleVisibleSelection } from './bulkSelection'

describe('bulk selection helpers', () => {
  it('chunks deterministically without losing order', () => {
    expect(chunkSelection(['a', 'b', 'c'], 2)).toEqual([['a', 'b'], ['c']])
  })
  it('reports all and partial selection among visible rows only', () => {
    expect(selectionState(['a', 'b'], new Set(['a', 'hidden']))).toEqual({ selectedVisible: 1, allVisibleSelected: false, partiallySelected: true })
    expect(selectionState(['a', 'b'], new Set(['a', 'b']))).toMatchObject({ allVisibleSelected: true, partiallySelected: false })
  })
  it('toggles only visible rows while preserving hidden selection', () => {
    expect([...toggleVisibleSelection(['a', 'b'], new Set(['a', 'hidden']))].sort()).toEqual(['a', 'b', 'hidden'])
    expect([...toggleVisibleSelection(['a', 'b'], new Set(['a', 'b', 'hidden']))].sort()).toEqual(['hidden'])
  })
})
