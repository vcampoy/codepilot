import type { AnalysisFinding } from './api'

export const FINDING_SEVERITIES = ['critical', 'high', 'medium', 'low'] as const
export type FindingSeverity = typeof FINDING_SEVERITIES[number]

const SEVERITY_ORDER: Record<FindingSeverity, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
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

export function sortFindings(findings: readonly AnalysisFinding[]): AnalysisFinding[] {
  return findings
    .map((finding, index) => ({ finding, index }))
    .sort((left, right) => {
      const severityDifference = SEVERITY_ORDER[displaySeverity(left.finding.severity)]
        - SEVERITY_ORDER[displaySeverity(right.finding.severity)]
      return severityDifference || left.index - right.index
    })
    .map(({ finding }) => finding)
}

export function severityCounts(findings: readonly AnalysisFinding[]): Record<FindingSeverity, number> {
  return findings.reduce<Record<FindingSeverity, number>>((counts, finding) => {
    counts[displaySeverity(finding.severity)] += 1
    return counts
  }, { critical: 0, high: 0, medium: 0, low: 0 })
}
