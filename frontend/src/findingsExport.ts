import type { AnalysisFinding } from './api'
import { categoryLabel, displaySeverity, type FindingFilters, type FindingSort } from './findingsPresentation'

const MARKDOWN_MIME_TYPE = 'text/markdown;charset=utf-8'

export interface FindingsMarkdownExportInput {
  repositoryUrl: string
  analysisId: string
  findings: readonly AnalysisFinding[]
  totalFindings?: number
  filters?: FindingFilters
  sort?: FindingSort
  exportedAt: Date
}

export interface FindingsMarkdownExportFile {
  filename: string
  content: string
}

export type ObjectUrlApi = Pick<typeof URL, 'createObjectURL' | 'revokeObjectURL'>

export function repositoryNameFromUrl(repositoryUrl: string): string {
  try {
    const parsedUrl = new URL(repositoryUrl)
    const pathSegments = parsedUrl.pathname.split('/').filter(Boolean)
    const repositorySegment = pathSegments.at(-1)?.replace(/\.git$/i, '') ?? ''
    const safeName = decodeURIComponent(repositorySegment)
      .replace(/[^a-zA-Z0-9._-]+/g, '-')
      .replace(/^-+|-+$/g, '')
    return safeName || 'repository'
  } catch {
    return 'repository'
  }
}

export function createFindingsMarkdownExport(input: FindingsMarkdownExportInput): FindingsMarkdownExportFile {
  const repositoryName = repositoryNameFromUrl(input.repositoryUrl)
  const timestamp = formatLocalTimestamp(input.exportedAt)
  const rows = input.findings.map(formatFindingRow).join('\n')
  const details = input.findings.map(formatFindingDetails).join('\n\n')
  const metadata = input.filters && input.sort
    ? [
        `- Total findings available: ${input.totalFindings ?? input.findings.length}`,
        `- Severity filter: ${formatFilterValues(input.filters.severities)}`,
        `- Type filter: ${formatFilterValues(input.filters.types)}`,
        `- Sort: ${formatSort(input.sort)}`,
      ]
    : []
  const content = [
    `# Findings for ${repositoryName}`,
    '',
    `- Repository: ${input.repositoryUrl}`,
    `- Analysis: ${input.analysisId}`,
    `- Exported at: ${input.exportedAt.toISOString()}`,
    `- Total findings: ${input.findings.length}`,
    ...metadata,
    '',
    '| Description | Severity | Rule | Location | Analyzer | Type |',
    '| --- | --- | --- | --- | --- | --- |',
    rows,
    ...(input.findings.length > 0 ? ['', '## Finding details', '', details] : []),
    '',
  ].join('\n')

  return {
    filename: `${repositoryName}-findings-${timestamp}.md`,
    content,
  }
}

function formatFilterValues(values: readonly string[]): string {
  return values.length > 0 ? values.join(', ') : 'All'
}

function formatSort(sort: FindingSort): string {
  const column = sort.column.charAt(0).toUpperCase() + sort.column.slice(1)
  return `${column} (${sort.direction === 'asc' ? 'ascending' : 'descending'})`
}

export function downloadMarkdownFile(
  file: FindingsMarkdownExportFile,
  documentRef: Document = document,
  urlApi: ObjectUrlApi = URL,
): void {
  const blob = new Blob([file.content], { type: MARKDOWN_MIME_TYPE })
  const objectUrl = urlApi.createObjectURL(blob)
  const anchor = documentRef.createElement('a')
  anchor.href = objectUrl
  anchor.download = file.filename
  anchor.rel = 'noopener'
  documentRef.body.appendChild(anchor)
  try {
    anchor.click()
  } finally {
    documentRef.body.removeChild(anchor)
    urlApi.revokeObjectURL(objectUrl)
  }
}

function formatFindingRow(finding: AnalysisFinding): string {
  const location = finding.start_line === finding.end_line
    ? `${finding.path}:${finding.start_line}`
    : `${finding.path}:${finding.start_line}-${finding.end_line}`
  return `| ${escapeMarkdownCell(finding.message)} | ${displaySeverity(finding.severity)} | ${escapeMarkdownCell(finding.rule_id)} | ${escapeMarkdownCell(location)} | ${escapeMarkdownCell(finding.analyzer)} | ${escapeMarkdownCell(categoryLabel(finding.category))} |`
}

function formatFindingDetails(finding: AnalysisFinding, index: number): string {
  const title = finding.title?.trim() || finding.rule_id
  return [
    `### ${index + 1}. [${displaySeverity(finding.severity)}] ${escapeMarkdownInline(title)}`,
    '',
    `- Type: ${escapeMarkdownInline(categoryLabel(finding.category))}`,
    `- Rule: ${escapeMarkdownInline(finding.rule_id)}`,
    `- Location: ${escapeMarkdownInline(formatLocation(finding))}`,
    `- Analyzer: ${escapeMarkdownInline(finding.analyzer)}`,
    '',
    '**Description**',
    '',
    formatMarkdownBlock(finding.message),
    '',
    '**Evidence**',
    '',
    formatOptionalMarkdownBlock(finding.evidence),
    '',
    '**Remediation**',
    '',
    formatOptionalMarkdownBlock(finding.remediation),
  ].join('\n')
}

function formatLocation(finding: AnalysisFinding): string {
  return finding.start_line === finding.end_line
    ? `${finding.path}:${finding.start_line}`
    : `${finding.path}:${finding.start_line}-${finding.end_line}`
}

function formatOptionalMarkdownBlock(value: string | null | undefined): string {
  return value?.trim() ? formatMarkdownBlock(value) : '_Not provided by analyzer._'
}

function formatMarkdownBlock(value: string): string {
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
    .replaceAll('\r\n', '\n')
    .replaceAll('\r', '\n')
    .split('\n')
    .map((line) => `> ${line}`)
    .join('\n')
}

function escapeMarkdownInline(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('\\', '\\\\')
    .replaceAll('`', '\\`')
    .replaceAll('[', '\\[')
    .replaceAll(']', '\\]')
    .replaceAll('\r\n', '<br>')
    .replaceAll('\n', '<br>')
    .replaceAll('\r', '<br>')
}

function escapeMarkdownCell(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('\\', '\\\\')
    .replaceAll('|', '\\|')
    .replaceAll('\r\n', '<br>')
    .replaceAll('\n', '<br>')
    .replaceAll('\r', '<br>')
}

function formatLocalTimestamp(value: Date): string {
  return [
    value.getFullYear().toString().padStart(4, '0'),
    (value.getMonth() + 1).toString().padStart(2, '0'),
    value.getDate().toString().padStart(2, '0'),
    value.getHours().toString().padStart(2, '0'),
    value.getMinutes().toString().padStart(2, '0'),
    value.getSeconds().toString().padStart(2, '0'),
  ].join('-')
}
