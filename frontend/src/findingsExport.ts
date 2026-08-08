import type { AnalysisFinding } from './api'

const MARKDOWN_MIME_TYPE = 'text/markdown;charset=utf-8'

export interface FindingsMarkdownExportInput {
  repositoryUrl: string
  analysisId: string
  findings: readonly AnalysisFinding[]
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
  const content = [
    `# Findings for ${repositoryName}`,
    '',
    `- Repository: ${input.repositoryUrl}`,
    `- Analysis: ${input.analysisId}`,
    `- Exported at: ${input.exportedAt.toISOString()}`,
    `- Total findings: ${input.findings.length}`,
    '',
    '| Severity | Rule | Location | Analyzer | Message |',
    '| --- | --- | --- | --- | --- |',
    rows,
    '',
  ].join('\n')

  return {
    filename: `${repositoryName}-findings-${timestamp}.md`,
    content,
  }
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
  return `| ${escapeMarkdownCell(finding.severity)} | ${escapeMarkdownCell(finding.rule_id)} | ${escapeMarkdownCell(location)} | ${escapeMarkdownCell(finding.analyzer)} | ${escapeMarkdownCell(finding.message)} |`
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
