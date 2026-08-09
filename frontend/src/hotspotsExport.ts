import type { FileDetail, FileInsight } from './api'
import { repositoryNameFromUrl, type FindingsMarkdownExportFile } from './findingsExport'
import { formatHotspotComponents, hotspotRisk, type HotspotFilters, type HotspotSort } from './hotspotsPresentation'

export interface HotspotsMarkdownExportInput {
  repositoryUrl: string
  analysisId: string
  hotspots: readonly FileInsight[]
  totalHotspotsLoaded?: number
  filters?: HotspotFilters
  sort?: HotspotSort
  details?: Readonly<Record<string, FileDetail | null | undefined>>
  exportedAt: Date
}

export const MAX_HOTSPOTS_EXPORT = 20

export function createHotspotsMarkdownExport(input: HotspotsMarkdownExportInput): FindingsMarkdownExportFile {
  const repositoryName = repositoryNameFromUrl(input.repositoryUrl)
  const timestamp = formatLocalTimestamp(input.exportedAt)
  const details = input.details ?? {}
  const metadata = input.filters && input.sort
    ? [`- Risk filter: ${input.filters.risks.length > 0 ? input.filters.risks.join(', ') : 'All'}`, `- Sort: ${formatSort(input.sort)}`]
    : []
  const sections = input.hotspots.map((hotspot, index) => formatHotspot(hotspot, details[hotspot.path], index + 1)).join('\n\n')
  const content = [
    `# Hotspots for ${repositoryName}`,
    '',
    `- Repository: ${escapeInline(input.repositoryUrl)}`,
    `- Analysis: ${escapeInline(input.analysisId)}`,
    `- Exported at: ${input.exportedAt.toISOString()}`,
    `- Total hotspots: ${input.hotspots.length}`,
    `- Total hotspots loaded: ${input.totalHotspotsLoaded ?? input.hotspots.length}`,
    ...metadata,
    '',
    '## Instructions for the coding model',
    '',
    'Resolve each hotspot using only the evidence in this document. Do not invent evidence, code, findings, or repository context. If evidence is unavailable, say so explicitly and request the missing context.',
    'Return a concrete remediation plan, proposed change, tests to run, and risks. Preserve behavior unless the evidence justifies a change.',
    '',
    sections,
    '',
  ].join('\n')
  return { filename: `${repositoryName}-hotspots-${timestamp}.md`, content }
}

function formatHotspot(hotspot: FileInsight, detail: FileDetail | null | undefined, index: number): string {
  const risk = hotspot.risk ? `${hotspot.risk.score.toFixed(2)} (${hotspotRisk(hotspot)})` : 'Unavailable'
  const findings = detail?.findings ?? []
  return [
    `## ${index}. ${escapeInline(hotspot.path)}`,
    '',
    `- Hotspot score: ${hotspot.hotspot_score.toFixed(2)}`,
    `- Risk: ${risk}`,
    `- Risk version: ${escapeInline(hotspot.risk?.version ?? 'Unavailable')}`,
    `- Components: ${escapeInline(formatHotspotComponents(hotspot))}`,
    '',
    '### Related findings',
    '',
    detail ? (findings.length > 0 ? findings.map((finding) => formatFinding(finding)).join('\n') : 'Related findings: _No related findings._') : 'Related findings: _Unavailable; file detail could not be loaded._',
  ].join('\n')
}

function formatFinding(finding: FileDetail['findings'][number]): string {
  const location = finding.start_line === finding.end_line ? `${finding.path}:${finding.start_line}` : `${finding.path}:${finding.start_line}-${finding.end_line}`
  return [
    `- **${escapeInline(finding.severity)}** ${escapeInline(finding.rule_id)} at ${escapeInline(location)} (${escapeInline(finding.analyzer)}): ${escapeInline(finding.message)}`,
    `  - Title: ${finding.title?.trim() ? escapeInline(finding.title) : '_Not provided by analyzer._'}`,
    `  - Type: ${escapeInline(finding.category?.trim() || 'Other')}`,
    `  - Evidence: ${finding.evidence?.trim() ? escapeInline(finding.evidence) : '_Not provided by analyzer._'}`,
    `  - Remediation: ${finding.remediation?.trim() ? escapeInline(finding.remediation) : '_Not provided by analyzer._'}`,
  ].join('\n')
}

function formatSort(sort: HotspotSort): string {
  const column = sort.column === 'hotspot_score' ? 'Hotspot score' : sort.column.charAt(0).toUpperCase() + sort.column.slice(1)
  return `${column} (${sort.direction === 'asc' ? 'ascending' : 'descending'})`
}

function escapeInline(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('\\', '\\\\')
    .replaceAll('`', '\\`')
    .replaceAll('*', '\\*')
    .replaceAll('_', '\\_')
    .replaceAll('[', '\\[')
    .replaceAll(']', '\\]')
    .replaceAll('|', '\\|')
    .replaceAll('\r\n', '<br>')
    .replaceAll('\n', '<br>')
    .replaceAll('\r', '<br>')
}

function formatLocalTimestamp(value: Date): string {
  return [value.getFullYear().toString().padStart(4, '0'), (value.getMonth() + 1).toString().padStart(2, '0'), value.getDate().toString().padStart(2, '0'), value.getHours().toString().padStart(2, '0'), value.getMinutes().toString().padStart(2, '0'), value.getSeconds().toString().padStart(2, '0')].join('-')
}
