export const HISTORY_DATE_FORMATTER = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' })

export function formatHistoryRisk(score: number | null, category: string | null): string {
  if (score === null) return '—'
  return `${score.toFixed(2)}${category ? ` (${category})` : ''}`
}

export function formatHistoryDate(createdAt: string): string {
  return HISTORY_DATE_FORMATTER.format(new Date(createdAt))
}

export function isHistoryActivationKey(key: string): boolean {
  return key === 'Enter' || key === ' '
}

export function totalHotspots(hotspotCount: number | undefined): number {
  return hotspotCount ?? 0
}
