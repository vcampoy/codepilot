export type AnalysisStatus = 'queued' | 'running' | 'completed' | 'failed'

export interface AnalysisAccepted {
  analysis_id: string
  status: AnalysisStatus
  project_id?: string | null
}

export interface Project { project_id: string; name: string; repository_url: string; created_at: string; updated_at: string }
export interface ProjectListResponse { items: Project[]; total: number; limit: number; offset: number }
export interface AnalysisRun { analysis_id: string; project_id: string | null; status: AnalysisStatus; repository_url: string; created_at: string; failure_message: string | null }
export interface AnalysisRunListResponse { items: AnalysisRun[]; total: number; limit: number; offset: number }

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
    risk_assessment?: RiskAssessment | null
    quality_gate?: QualityGate | null
    quality_policy?: QualityPolicy | null
    baseline_analysis_id?: string | null
    hotspot_count?: number
  } | null
}

export interface RiskAssessment { score: number; category: string; version: string; components: Record<string, number>; weights: Record<string, number> }
export interface QualityGateFailure { code: string; detail: string }
export interface QualityGateThresholds { max_new_critical_findings: number | null; max_risk_score: number | null; max_new_hotspots: number | null }
export interface QualityGateObserved { new_critical_findings: number; risk_score: number | null; new_hotspots: number }
export interface QualityGate { passed: boolean; configured: boolean; status: 'passed' | 'failed' | 'not_configured'; failures: QualityGateFailure[]; thresholds: QualityGateThresholds; observed: QualityGateObserved }
export interface QualityRule { language: string; analyzer: string; rule_id: string; enabled: boolean }
export interface QualityProfile { language: string; rules: QualityRule[] }
export interface QualityPolicy { version: number; configured: boolean; max_new_critical_findings: number | null; max_risk_score: number | null; max_new_hotspots: number | null; profiles: QualityProfile[] }
export interface FileInsight { path: string; hotspot_score: number; risk: RiskAssessment | null; metrics: Record<string, number> }
export interface FileDetail extends FileInsight { findings: AnalysisFinding[] }
export interface AnalysisFilesResponse { items: FileInsight[]; total: number; limit: number; offset: number }

export interface AnalyzerOutcome { analyzer: string; tool: string; version: string | null; status: string; duration_seconds: number; message: string | null; language?: string | null; generic?: boolean }
export interface AnalysisFinding {
  path: string
  rule_id: string
  analyzer: string
  severity: string
  message: string
  start_line: number
  end_line: number
  category?: string
  title?: string | null
  evidence?: string | null
  remediation?: string | null
  source_context?: SourceContext | null
}

export interface SourceContextLine { number: number; text: string; highlighted?: boolean }
export interface SourceContext { start_line: number; end_line: number; lines: SourceContextLine[] }

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

export interface LlmConfiguration {
  enabled: boolean
  provider: string
  model: string
  api_key_configured: boolean
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

export function getProjects(limit = 20, offset = 0): Promise<ProjectListResponse> {
  return request<ProjectListResponse>(`/api/v1/projects?limit=${limit}&offset=${offset}`)
}

export function getProjectAnalyses(projectId: string, limit = 20, offset = 0): Promise<AnalysisRunListResponse> {
  return request<AnalysisRunListResponse>(`/api/v1/projects/${encodeURIComponent(projectId)}/analyses?limit=${limit}&offset=${offset}`)
}

export function getQualityPolicy(projectId: string): Promise<QualityPolicy> {
  return request<QualityPolicy>(`/api/v1/projects/${encodeURIComponent(projectId)}/quality-policy`)
}

export function saveQualityPolicy(projectId: string, policy: Omit<QualityPolicy, 'configured'>): Promise<QualityPolicy> {
  return request<QualityPolicy>(`/api/v1/projects/${encodeURIComponent(projectId)}/quality-policy`, { method: 'PUT', body: JSON.stringify(policy) })
}

export function importQualityProfile(projectId: string, xml: string): Promise<{ language: string; profile_name: string | null; mapped: number; unsupported: string[]; invalid: string[] }> {
  return request(`/api/v1/projects/${encodeURIComponent(projectId)}/quality-profiles/import`, { method: 'POST', body: xml, headers: { 'Content-Type': 'application/xml' } })
}

export function getAnalysisFindings(id: string, init?: RequestInit): Promise<AnalysisFinding[]> {
  return request<AnalysisFinding[]>(`/api/v1/analyses/${encodeURIComponent(id)}/findings`, init)
}

export function getAnalysisHotspots(id: string, limit = 20, init?: RequestInit): Promise<FileInsight[]> {
  return request<FileInsight[]>(
    `/api/v1/analyses/${encodeURIComponent(id)}/hotspots?limit=${limit}`,
    init,
  )
}

export function getAnalysisFiles(id: string, limit = 100, offset = 0, init?: RequestInit): Promise<AnalysisFilesResponse> {
  return request<AnalysisFilesResponse>(
    `/api/v1/analyses/${encodeURIComponent(id)}/files?limit=${limit}&offset=${offset}`,
    init,
  )
}

export function getAnalysisFileDetail(id: string, path: string, init?: RequestInit): Promise<FileDetail> {
  return request<FileDetail>(
    `/api/v1/analyses/${encodeURIComponent(id)}/files/detail?path=${encodeURIComponent(path)}`,
    init,
  )
}

export function requestEnrichment(id: string, task: EnrichmentTask, path?: string): Promise<EnrichmentResponse> {
  const query = path ? `?path=${encodeURIComponent(path)}` : ''
  return request<EnrichmentResponse>(
    `/api/v1/analyses/${encodeURIComponent(id)}/enrichment/${task}${query}`,
    { method: 'POST' },
  )
}

export function getLlmConfiguration(): Promise<LlmConfiguration> {
  return request<LlmConfiguration>('/api/v1/settings/llm')
}

export function saveLlmConfiguration(payload: { enabled: boolean; provider: string; model: string; api_key?: string }): Promise<LlmConfiguration> {
  return request<LlmConfiguration>('/api/v1/settings/llm', { method: 'PUT', body: JSON.stringify(payload) })
}

export const apiDocsUrl = `${apiBaseUrl}/docs`
