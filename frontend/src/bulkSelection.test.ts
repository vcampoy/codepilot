import { describe, expect, it } from 'vitest'
import { chunkSelection, selectionState, toggleVisibleSelection, toggleSelection, limitSelection } from './bulkSelection'

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
  it('limits selection to the configured maximum in visible order', () => {
    expect([...toggleVisibleSelection(['a', 'b', 'c'], new Set(), 2)]).toEqual(['a', 'b'])
    expect([...toggleVisibleSelection(['a', 'b', 'c'], new Set(['hidden']), 2)]).toEqual(['hidden', 'a'])
  })
  it('does not add an unselected item when the limit is reached', () => {
    expect([...toggleSelection('c', new Set(['a', 'b']), 2)]).toEqual(['a', 'b'])
  })
  it('prunes selection deterministically when the maximum changes', () => {
    expect([...limitSelection(new Set(['b', 'a', 'c']), 2)]).toEqual(['b', 'a'])
  })
})
