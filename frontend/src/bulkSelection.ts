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

export function toggleVisibleSelection(
  visibleIds: readonly string[],
  selectedIds: ReadonlySet<string>,
): Set<string> {
  const next = new Set(selectedIds)
  const { allVisibleSelected } = selectionState(visibleIds, selectedIds)
  visibleIds.forEach((id) => (allVisibleSelected ? next.delete(id) : next.add(id)))
  return next
}
