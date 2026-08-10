import { describe, expect, it } from 'vitest'
import type { AnalysisFinding } from './api'
import {
  categoryLabel,
  displaySeverity,
  filterFindings,
  reconcileFindingSort,
  severityCounts,
  sortFindings,
  toggleFindingSort,
  type FindingSort,
} from './findingsPresentation'

const finding = (severity: string, rule_id: string, message = rule_id, category = 'style'): AnalysisFinding => ({
  path: 'src/example.ts', rule_id, analyzer: 'test', severity, message, category, start_line: 1, end_line: 1,
})

const SORT_FIXTURE: readonly AnalysisFinding[] = [
  finding('low', 'third', 'zebra', 'security'),
  finding('critical', 'first', 'Alpha', 'dependency_graph'),
  finding('medium', 'second', 'beta', 'style'),
  finding('high', 'fourth', 'alpha', 'performance'),
]

describe('findings presentation', () => {
  it('filters by selected severities and types without mutating input', () => {
    const findings = [
      finding('critical', 'critical-style', 'Critical style', 'style'),
      finding('warning', 'warning-security', 'Warning security', 'security'),
      finding('info', 'info-style', 'Info style', 'style'),
    ] as const

    expect(filterFindings(findings, { severities: ['critical', 'low'], types: ['Style'] }).map((item) => item.rule_id))
      .toEqual(['critical-style', 'info-style'])
    expect(filterFindings(findings, { severities: ['high'], types: [] })).toEqual([])
    expect(findings.map((item) => item.rule_id)).toEqual(['critical-style', 'warning-security', 'info-style'])
  })

  it('returns every finding when no filters are selected', () => {
    const findings = [finding('critical', 'one'), finding('low', 'two')] as const
    expect(filterFindings(findings, { severities: [], types: [] })).toEqual(findings)
  })
  it.each([
    ['critical', 'critical'], ['high', 'high'], ['error', 'high'], ['medium', 'medium'],
    ['warning', 'medium'], ['low', 'low'], ['info', 'low'], ['note', 'low'], ['unexpected', 'medium'],
  ])('maps %s to %s', (raw, expected) => {
    expect(displaySeverity(raw)).toBe(expected)
  })

  it('labels categories and falls back to Other', () => {
    expect(categoryLabel('dependency_graph')).toBe('Dependency Graph')
    expect(categoryLabel(undefined)).toBe('Other')
    expect(categoryLabel('')).toBe('Other')
  })

  it('counts and sorts findings by severity while preserving ties', () => {
    const findings = [
      finding('info', 'low'),
      finding('error', 'high'),
      finding('critical', 'critical'),
      finding('warning', 'medium'),
      finding('error', 'high-2'),
    ]
    expect(sortFindings(findings, { column: 'severity', direction: 'desc' }).map((item) => item.rule_id)).toEqual(['critical', 'high', 'high-2', 'medium', 'low'])
    expect(severityCounts(findings)).toEqual({ critical: 1, high: 2, medium: 1, low: 1 })
  })

  it.each([
    ['description', 'asc', ['first', 'fourth', 'second', 'third']],
    ['description', 'desc', ['third', 'second', 'first', 'fourth']],
    ['severity', 'asc', ['third', 'second', 'fourth', 'first']],
    ['severity', 'desc', ['first', 'fourth', 'second', 'third']],
    ['type', 'asc', ['first', 'fourth', 'third', 'second']],
    ['type', 'desc', ['second', 'third', 'fourth', 'first']],
  ] as const)('sorts by %s in %s order', (column, direction, expected) => {
    expect(sortFindings(SORT_FIXTURE, { column, direction }).map((item) => item.rule_id)).toEqual(expected)
  })

  it('sorts case-insensitively, preserves ties, and does not mutate input', () => {
    const findings = [
      finding('low', 'tie-1', 'Same'),
      finding('low', 'tie-2', 'same'),
      finding('low', 'tie-3', 'other'),
    ] as const
    const original = findings.map((item) => item.rule_id)
    expect(
      sortFindings(findings, { column: 'description', direction: 'asc' }).map((item) => item.rule_id),
    ).toEqual(['tie-3', 'tie-1', 'tie-2'])
    expect(findings.map((item) => item.rule_id)).toEqual(original)
  })

  it('toggles direction on the active column and starts ascending for a new column', () => {
    const initial: FindingSort = { column: 'severity', direction: 'desc' }
    expect(toggleFindingSort(initial, 'severity')).toEqual({ column: 'severity', direction: 'asc' })
    expect(toggleFindingSort(initial, 'description')).toEqual({ column: 'description', direction: 'asc' })
  })

  it('reconciles a hidden sort column after visibility changes', () => {
    const current: FindingSort = { column: 'severity', direction: 'desc' }
    expect(reconcileFindingSort(current, ['description', 'type'])).toEqual({ column: 'description', direction: 'asc' })
    expect(reconcileFindingSort(current, [])).toEqual(current)
    expect(reconcileFindingSort(current, ['severity'])).toEqual(current)
  })
})
