import type { AnalysisFinding } from './api'

export const FINDING_SEVERITIES = ['critical', 'high', 'medium', 'low'] as const
export type FindingSeverity = typeof FINDING_SEVERITIES[number]

export type FindingColumnKey = 'description' | 'severity' | 'type'
export type SortDirection = 'asc' | 'desc'
export type FindingSort = { column: FindingColumnKey; direction: SortDirection }
export type FindingFilters = {
  severities: readonly FindingSeverity[]
  types: readonly string[]
}

export const FINDING_COLUMNS: readonly { key: FindingColumnKey; label: string }[] = [
  { key: 'description', label: 'Description' },
  { key: 'severity', label: 'Severity' },
  { key: 'type', label: 'Type' },
] as const

const DEFAULT_FINDING_SORT: FindingSort = { column: 'severity', direction: 'desc' }

const SEVERITY_ORDER: Record<FindingSeverity, number> = {
  low: 0,
  medium: 1,
  high: 2,
  critical: 3,
}

export function displaySeverity(rawSeverity: string): FindingSeverity {
  switch (rawSeverity.trim().toLowerCase()) {
    case 'critical':
      return 'critical'
    case 'high':
    case 'error':
      return 'high'
    case 'medium':
    case 'warning':
      return 'medium'
    case 'low':
    case 'info':
    case 'note':
      return 'low'
    default:
      return 'medium'
  }
}

export function categoryLabel(category: string | undefined): string {
  const normalized = category?.trim().toLowerCase()
  if (!normalized) return 'Other'
  return normalized
    .split(/[-_\s]+/)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

export function filterFindings(
  findings: readonly AnalysisFinding[],
  filters: FindingFilters,
): AnalysisFinding[] {
  const severityFilter = new Set(filters.severities)
  const typeFilter = new Set(filters.types.map((type) => type.trim().toLowerCase()))
  return findings.filter((finding) => {
    const severityMatches = severityFilter.size === 0 || severityFilter.has(displaySeverity(finding.severity))
    const typeMatches = typeFilter.size === 0 || typeFilter.has(categoryLabel(finding.category).toLowerCase())
    return severityMatches && typeMatches
  })
}

export function sortFindings(
  findings: readonly AnalysisFinding[],
  sort: FindingSort = DEFAULT_FINDING_SORT,
): AnalysisFinding[] {
  return findings
    .map((finding, index) => ({ finding, index }))
    .sort((left, right) => {
      const leftValue = sortValue(left.finding, sort.column)
      const rightValue = sortValue(right.finding, sort.column)
      const difference = typeof leftValue === 'number' && typeof rightValue === 'number'
        ? leftValue - rightValue
        : String(leftValue).localeCompare(String(rightValue), undefined, { sensitivity: 'base' })
      return (sort.direction === 'desc' ? -difference : difference) || left.index - right.index
    })
    .map(({ finding }) => finding)
}

function sortValue(finding: AnalysisFinding, column: FindingColumnKey): string | number {
  switch (column) {
    case 'description':
      return finding.message
    case 'severity':
      return SEVERITY_ORDER[displaySeverity(finding.severity)]
    case 'type':
      return categoryLabel(finding.category)
  }
}

export function toggleFindingSort(current: FindingSort, column: FindingColumnKey): FindingSort {
  return current.column === column
    ? { column, direction: current.direction === 'asc' ? 'desc' : 'asc' }
    : { column, direction: 'asc' }
}

export function reconcileFindingSort(current: FindingSort, visibleColumns: readonly FindingColumnKey[]): FindingSort {
  if (visibleColumns.length === 0 || visibleColumns.includes(current.column)) return current
  const firstVisible = FINDING_COLUMNS.find(({ key }) => visibleColumns.includes(key))?.key
  return firstVisible ? { column: firstVisible, direction: 'asc' } : current
}

export function severityCounts(findings: readonly AnalysisFinding[]): Record<FindingSeverity, number> {
  return findings.reduce<Record<FindingSeverity, number>>((counts, finding) => {
    counts[displaySeverity(finding.severity)] += 1
    return counts
  }, { critical: 0, high: 0, medium: 0, low: 0 })
}
