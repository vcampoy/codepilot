export type AnalysisStatus = 'queued' | 'running' | 'completed' | 'failed'

export interface AnalysisAccepted {
  analysis_id: string
  status: AnalysisStatus
}

export interface AnalysisStatusResponse {
  analysis_id: string
  status: AnalysisStatus
  commit_sha: string | null
  failure_message: string | null
  retryable: boolean
}

export interface AnalysisSummaryResponse {
  analysis_id: string
  status: AnalysisStatus
  summary: {
    analyzed_file_count: number
    source_lines: number
    finding_count_by_severity: Record<string, number>
    duration_seconds: number
    analyzer_outcomes?: AnalyzerOutcome[]
  } | null
}

export interface AnalyzerOutcome { analyzer: string; tool: string; version: string | null; status: string; duration_seconds: number; message: string | null; language?: string | null; generic?: boolean }
export interface AnalysisFinding { path: string; rule_id: string; analyzer: string; severity: string; message: string; start_line: number; end_line: number }

export interface AnalyzerAvailability {
  analyzer: string
  status: 'available' | 'skipped' | 'not_requested'
  tool: string
}

export type EnrichmentTask = 'file-risk' | 'refactoring-plan' | 'deterministic-summary'

export interface EnrichmentResponse {
  task: EnrichmentTask
  analysis_id: string
  enabled: boolean
  ai_generated: boolean
  text: string | null
  structured: Record<string, unknown> | null
  citations: string[]
  model: string | null
  provider: string | null
  latency_ms: number
  cache_hit: boolean
}

const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim()
const apiBaseUrl = (configuredBaseUrl || 'http://localhost:8000').replace(/\/+$/, '')

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { message?: string; detail?: string } | null
    throw new Error(payload?.message || payload?.detail || `Request failed with HTTP ${response.status}.`)
  }
  return (await response.json()) as T
}

export function createAnalysis(repositoryUrl: string): Promise<AnalysisAccepted> {
  return request<AnalysisAccepted>('/api/v1/analyses', {
    method: 'POST',
    body: JSON.stringify({ repository_url: repositoryUrl }),
  })
}

export function getAnalysisStatus(id: string): Promise<AnalysisStatusResponse> {
  return request<AnalysisStatusResponse>(`/api/v1/analyses/${encodeURIComponent(id)}`)
}

export function getAnalysisSummary(id: string): Promise<AnalysisSummaryResponse> {
  return request<AnalysisSummaryResponse>(
    `/api/v1/analyses/${encodeURIComponent(id)}/summary`,
  )
}

export function getAnalyzerAvailability(): Promise<AnalyzerAvailability[]> {
  return request<AnalyzerAvailability[]>('/api/v1/analyses/analyzers/availability')
}

export function getAnalysisFindings(id: string): Promise<AnalysisFinding[]> {
  return request<AnalysisFinding[]>(`/api/v1/analyses/${encodeURIComponent(id)}/findings`)
}

export function requestEnrichment(id: string, task: EnrichmentTask, path?: string): Promise<EnrichmentResponse> {
  const query = path ? `?path=${encodeURIComponent(path)}` : ''
  return request<EnrichmentResponse>(
    `/api/v1/analyses/${encodeURIComponent(id)}/enrichment/${task}${query}`,
    { method: 'POST' },
  )
}

export const apiDocsUrl = `${apiBaseUrl}/docs`
