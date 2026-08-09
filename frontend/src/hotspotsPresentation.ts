import type { FileInsight } from './api'

export const HOTSPOT_RISKS = ['critical', 'high', 'medium', 'low', 'unavailable'] as const
export type HotspotRisk = typeof HOTSPOT_RISKS[number]
export type HotspotColumnKey = 'file' | 'hotspot_score' | 'risk' | 'components'
export type SortDirection = 'asc' | 'desc'
export type HotspotSort = { column: HotspotColumnKey; direction: SortDirection }
export type HotspotFilters = { risks: readonly HotspotRisk[] }

export const HOTSPOT_COLUMNS: readonly { key: HotspotColumnKey; label: string }[] = [
  { key: 'file', label: 'File' },
  { key: 'hotspot_score', label: 'Hotspot score' },
  { key: 'risk', label: 'Risk' },
  { key: 'components', label: 'Components' },
] as const

const RISK_ORDER: Record<HotspotRisk, number> = { low: 0, medium: 1, high: 2, critical: 3, unavailable: Number.POSITIVE_INFINITY }

export function hotspotRisk(hotspot: FileInsight): HotspotRisk {
  const normalized = hotspot.risk?.category?.trim().toLowerCase()
  return HOTSPOT_RISKS.includes(normalized as HotspotRisk) ? normalized as HotspotRisk : 'unavailable'
}

export function hotspotComponentCount(hotspot: FileInsight): number {
  return Object.keys(hotspot.metrics).length
}

export function formatHotspotComponents(hotspot: FileInsight): string {
  const entries = Object.entries(hotspot.metrics).sort(([left], [right]) => left.localeCompare(right))
  return entries.length > 0 ? entries.map(([name, value]) => `${name}: ${value.toFixed(2)}`).join(' · ') : 'Unavailable'
}

export function filterHotspots(hotspots: readonly FileInsight[], filters: HotspotFilters): FileInsight[] {
  const selected = new Set(filters.risks)
  return hotspots.filter((hotspot) => selected.size === 0 || selected.has(hotspotRisk(hotspot)))
}

export function sortHotspots(hotspots: readonly FileInsight[], sort: HotspotSort = { column: 'hotspot_score', direction: 'desc' }): FileInsight[] {
  return hotspots
    .map((hotspot, index) => ({ hotspot, index }))
    .sort((left, right) => {
      const leftMissing = isMissingSortValue(left.hotspot, sort.column)
      const rightMissing = isMissingSortValue(right.hotspot, sort.column)
      if (leftMissing || rightMissing) {
        if (leftMissing && rightMissing) return left.index - right.index
        return leftMissing ? 1 : -1
      }
      const leftValue = sortValue(left.hotspot, sort.column)
      const rightValue = sortValue(right.hotspot, sort.column)
      const difference = typeof leftValue === 'number' && typeof rightValue === 'number'
        ? leftValue - rightValue
        : String(leftValue).localeCompare(String(rightValue), undefined, { sensitivity: 'base' })
      return (sort.direction === 'desc' ? -difference : difference) || left.index - right.index
    })
    .map(({ hotspot }) => hotspot)
}

function isMissingSortValue(hotspot: FileInsight, column: HotspotColumnKey): boolean {
  return column === 'risk'
    ? hotspotRisk(hotspot) === 'unavailable'
    : column === 'components' && hotspotComponentCount(hotspot) === 0
}

function sortValue(hotspot: FileInsight, column: HotspotColumnKey): string | number {
  switch (column) {
    case 'file': return hotspot.path
    case 'hotspot_score': return hotspot.hotspot_score
    case 'risk': return RISK_ORDER[hotspotRisk(hotspot)]
    case 'components': return hotspotComponentCount(hotspot)
  }
}

export function toggleHotspotSort(current: HotspotSort, column: HotspotColumnKey): HotspotSort {
  return current.column === column
    ? { column, direction: current.direction === 'asc' ? 'desc' : 'asc' }
    : { column, direction: 'asc' }
}
