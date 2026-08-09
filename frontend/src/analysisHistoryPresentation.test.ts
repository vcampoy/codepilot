import { describe, expect, it } from 'vitest'
import { formatHistoryDate, formatHistoryRisk, isHistoryActivationKey, totalHotspots } from './analysisHistoryPresentation'

const HISTORY_SCORE = 0.8

describe('analysis history presentation', () => {
  it('formats risk score and category while preserving an empty score', () => {
    expect(formatHistoryRisk(HISTORY_SCORE, 'high')).toBe('0.80 (high)')
    expect(formatHistoryRisk(HISTORY_SCORE, null)).toBe('0.80')
    expect(formatHistoryRisk(null, null)).toBe('—')
  })

  it('formats stored UTC dates for the user locale', () => {
    const formatted = formatHistoryDate('2026-08-09T12:00:00Z')
    expect(formatted).toContain('2026')
    expect(formatted).toMatch(/\d{1,2}:\d{2}/)
  })

  it('accepts only keyboard activation keys', () => {
    expect(isHistoryActivationKey('Enter')).toBe(true)
    expect(isHistoryActivationKey(' ')).toBe(true)
    expect(isHistoryActivationKey('Escape')).toBe(false)
  })

  it('uses the persisted hotspot total and defaults missing data to zero', () => {
    expect(totalHotspots(11)).toBe(11)
    expect(totalHotspots(undefined)).toBe(0)
  })
})
