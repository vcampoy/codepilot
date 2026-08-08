import { describe, expect, it } from 'vitest'
import type { AnalysisFinding } from './api'
import { categoryLabel, displaySeverity, severityCounts, sortFindings } from './findingsPresentation'

const finding = (severity: string, rule_id: string): AnalysisFinding => ({
  path: 'src/example.ts', rule_id, analyzer: 'test', severity, message: rule_id, start_line: 1, end_line: 1,
})

describe('findings presentation', () => {
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
    const findings = [finding('info', 'low'), finding('error', 'high'), finding('critical', 'critical'), finding('warning', 'medium'), finding('error', 'high-2')]
    expect(sortFindings(findings).map((item) => item.rule_id)).toEqual(['critical', 'high', 'high-2', 'medium', 'low'])
    expect(severityCounts(findings)).toEqual({ critical: 1, high: 2, medium: 1, low: 1 })
  })
})
