import { describe, expect, it } from 'vitest'
import { getSelectionState, toggleAllHistorySelection, toggleHistorySelection } from './analysisHistorySelection'

const HISTORY_IDS = ['analysis-1', 'analysis-2', 'analysis-3'] as const

describe('analysis history selection', () => {
  it('toggles one analysis without mutating the previous selection', () => {
    const initial = new Set<string>(['analysis-1'])

    const next = toggleHistorySelection(initial, 'analysis-2')

    expect(next).toEqual(new Set(['analysis-1', 'analysis-2']))
    expect(initial).toEqual(new Set(['analysis-1']))
    expect(toggleHistorySelection(next, 'analysis-2')).toEqual(new Set(['analysis-1']))
  })

  it('selects and clears all visible history rows', () => {
    const selected = toggleAllHistorySelection(new Set<string>(), HISTORY_IDS, true)
    expect(selected).toEqual(new Set(HISTORY_IDS))

    expect(toggleAllHistorySelection(selected, HISTORY_IDS, false)).toEqual(new Set())
  })

  it('reports none, mixed, and all selection states for visible rows', () => {
    expect(getSelectionState(new Set(['analysis-1']), [])).toEqual({ checked: false, indeterminate: false })
    expect(getSelectionState(new Set(), HISTORY_IDS)).toEqual({ checked: false, indeterminate: false })
    expect(getSelectionState(new Set(['analysis-1']), HISTORY_IDS)).toEqual({ checked: false, indeterminate: true })
    expect(getSelectionState(new Set(HISTORY_IDS), HISTORY_IDS)).toEqual({ checked: true, indeterminate: false })
  })
})
