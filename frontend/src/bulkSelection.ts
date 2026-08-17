export const BULK_BATCH_SIZE = 10

export function chunkSelection<T>(items: readonly T[], size = BULK_BATCH_SIZE): T[][] {
  if (!Number.isInteger(size) || size < 1) throw new Error('Batch size must be a positive integer.')
  const batches: T[][] = []
  for (let index = 0; index < items.length; index += size) batches.push(items.slice(index, index + size))
  return batches
}

export function selectionState(visibleIds: readonly string[], selectedIds: ReadonlySet<string>) {
  const selectedVisible = visibleIds.reduce((count, id) => count + (selectedIds.has(id) ? 1 : 0), 0)
  return {
    selectedVisible,
    allVisibleSelected: visibleIds.length > 0 && selectedVisible === visibleIds.length,
    partiallySelected: selectedVisible > 0 && selectedVisible < visibleIds.length,
  }
}

/** Preserve insertion order while enforcing a selection cap. */
export function limitSelection(selectedIds: ReadonlySet<string>, max: number): Set<string> {
  const limit = Number.isFinite(max) ? Math.max(0, Math.floor(max)) : selectedIds.size
  return new Set([...selectedIds].slice(0, limit))
}

export function toggleSelection(id: string, selectedIds: ReadonlySet<string>, max = Number.POSITIVE_INFINITY): Set<string> {
  const next = limitSelection(selectedIds, max)
  if (next.has(id)) next.delete(id)
  else if (next.size < max) next.add(id)
  return next
}

export function toggleVisibleSelection(
  visibleIds: readonly string[],
  selectedIds: ReadonlySet<string>,
  max = Number.POSITIVE_INFINITY,
): Set<string> {
  const next = limitSelection(selectedIds, max)
  const { allVisibleSelected } = selectionState(visibleIds, selectedIds)
  visibleIds.forEach((id) => (allVisibleSelected ? next.delete(id) : next.add(id)))
  return limitSelection(next, max)
}
