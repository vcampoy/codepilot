export type SelectionState = {
  checked: boolean
  indeterminate: boolean
}

export function toggleHistorySelection(selected: ReadonlySet<string>, analysisId: string): Set<string> {
  const next = new Set(selected)
  if (next.has(analysisId)) next.delete(analysisId)
  else next.add(analysisId)
  return next
}

export function toggleAllHistorySelection(selected: ReadonlySet<string>, visibleIds: readonly string[], checked: boolean): Set<string> {
  const next = new Set(selected)
  visibleIds.forEach((id) => (checked ? next.add(id) : next.delete(id)))
  return next
}

export function getSelectionState(selected: ReadonlySet<string>, visibleIds: readonly string[]): SelectionState {
  const selectedVisibleCount = visibleIds.filter((id) => selected.has(id)).length
  return {
    checked: visibleIds.length > 0 && selectedVisibleCount === visibleIds.length,
    indeterminate: selectedVisibleCount > 0 && selectedVisibleCount < visibleIds.length,
  }
}
