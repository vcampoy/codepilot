import { useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { useId } from 'react'
import {
  apiDocsUrl,
  createAnalysis,
  getAnalysisStatus,
  getAnalysisSummary,
  getAnalysisFindings,
  getAnalysisFileDetail,
  getAnalysisHotspots,
  getAnalysisFiles,
  getProjects,
  getAnalysisHistory,
  deleteAnalysis,
  saveQualityPolicy,
  getQualityPolicy,
  importQualityProfile,
  getLlmConfiguration,

  getLlmProviders,

  saveLlmConfiguration,
  requestEnrichment,
  createFixJob,
  getFixConfiguration,
  getFixJob,
  saveFixConfiguration,
  type AnalysisStatus,
  type AnalysisSummaryResponse,
  type AnalysisFinding,
  type FileDetail,
  type FileInsight,
  type EnrichmentResponse,
  type Project,
  type AnalysisHistoryItem,
  type LlmConfiguration,
  type LlmProvider,
  type FixConfiguration,
  type FixJob,
} from './api'
import { deleteAnalyses, type AnalysisDeletionResult } from './analysisDeletion'
import { getSelectionState, toggleAllHistorySelection, toggleHistorySelection } from './analysisHistorySelection'
import { createFindingsMarkdownExport, downloadMarkdownFile } from './findingsExport'
import { createHotspotsMarkdownExport, MAX_HOTSPOTS_EXPORT } from './hotspotsExport'
import { TableFilterDialog } from './components/TableFilterDialog'
import { ConfirmationDialog } from './components/ConfirmationDialog'
import {
  formatHistoryDate,
  formatHistoryRisk,
  isHistoryActivationKey,
  totalHotspots,
} from './analysisHistoryPresentation'
import {
  FINDING_COLUMNS,
  FINDING_SEVERITIES,
  categoryLabel,
  displaySeverity,
  filterFindings,
  reconcileFindingSort,
  severityCounts,
  sortFindings,
  toggleFindingSort,
  type FindingColumnKey,
  type FindingFilters,
  type FindingSort,
} from './findingsPresentation'
import {
  HOTSPOT_COLUMNS,
  HOTSPOT_RISKS,
  filterHotspots,
  formatHotspotComponents,
  hotspotRisk,
  sortHotspots,
  toggleHotspotSort,
  type HotspotColumnKey,
  type HotspotFilters,
  type HotspotSort,
} from './hotspotsPresentation'

type View = 'repositories' | 'analyses' | 'overview' | 'findings' | 'hotspots' | 'files' | 'quality' | 'setup'

const views: { id: View; label: string; icon: string }[] = [
  { id: 'repositories', label: 'Repositories', icon: 'R' },
  { id: 'analyses', label: 'Analysis history', icon: 'A' },
  { id: 'overview', label: 'Overview', icon: 'O' },
  { id: 'findings', label: 'Findings', icon: 'F' },
  { id: 'hotspots', label: 'Hotspots', icon: 'H' },
  { id: 'files', label: 'File detail', icon: 'D' },
  { id: 'quality', label: 'Quality gate', icon: 'Q' },

  { id: 'setup', label: 'Setup', icon: 'S' },

]

function viewFromHash(): View {
  const candidate = window.location.hash.replace('#', '') as View
  return views.some((view) => view.id === candidate) ? candidate : 'repositories'
}

function AppliedFilterTags({ values }: { values: readonly string[] }) {
  if (values.length === 0) return null
  return (
    <ul aria-label="Applied filters" className="applied-filter-tags">
      {values.map((value) => <li key={value}>{value.charAt(0).toUpperCase() + value.slice(1)}</li>)}
    </ul>
  )
}

function canOpenWithoutAnalysis(view: View): boolean {

  return view === 'repositories' || view === 'analyses' || view === 'setup'

}

function activeViewFor(view: View, hasAnalysis: boolean): View {
  return hasAnalysis || canOpenWithoutAnalysis(view) ? view : 'repositories'
}

function RepositoriesView({
  projects,
  busy,
  error,
}: {
  projects: readonly Project[]
  busy: boolean
  error: string | null
}) {
  return (
    <section className="page-grid">
      <div className="panel table-panel">
        <div className="panel-title">
          <span>Persisted repositories</span>
          {!busy && <span className="muted">Latest updated first</span>}
        </div>
        {error && <p className="error-copy" role="alert">{error}</p>}
        {busy ? (
          <EmptyState title="Loading repositories" description="Reading persisted repositories." compact />
        ) : projects.length ? (
          <div className="history-table-wrap">
            <table className="history-table">
              <caption className="sr-only">Persisted repositories</caption>
              <thead>
                <tr>
                  <th scope="col">Repository</th>
                  <th scope="col">URL</th>
                  <th scope="col">Last updated</th>
                </tr>
              </thead>
              <tbody>
                {projects.map((project) => (
                  <tr key={project.project_id}>
                    <th scope="row">{project.name}</th>
                    <td>
                      <a className="repository-link" href={project.repository_url} rel="noreferrer" target="_blank">
                        {project.repository_url}
                      </a>
                    </td>
                    <td>{formatHistoryDate(project.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            title="No repositories yet"
            description="Your submitted repositories will appear here with their latest analysis."
            compact
          />
        )}
      </div>
    </section>
  )
}

function App() {
  const [view, setView] = useState<View>(viewFromHash)
  const [repositoryUrl, setRepositoryUrl] = useState('')
  const [analyzedRepositoryUrl, setAnalyzedRepositoryUrl] = useState<string | null>(null)
  const [analysisId, setAnalysisId] = useState<string | null>(null)
  const [status, setStatus] = useState<AnalysisStatus | null>(null)
  const [summary, setSummary] = useState<AnalysisSummaryResponse['summary']>(null)
  const [findings, setFindings] = useState<AnalysisFinding[]>([])
  const [hotspots, setHotspots] = useState<FileInsight[]>([])
  const [fileInsights, setFileInsights] = useState<FileInsight[]>([])
  const [findingsError, setFindingsError] = useState<string | null>(null)
  const [hotspotsError, setHotspotsError] = useState<string | null>(null)
  const [filesError, setFilesError] = useState<string | null>(null)
  const [resultsBusy, setResultsBusy] = useState(false)
  const [selectedFilePath, setSelectedFilePath] = useState<string | null>(null)
  const [projects, setProjects] = useState<Project[]>([])
  const [projectsBusy, setProjectsBusy] = useState(false)
  const [projectsError, setProjectsError] = useState<string | null>(null)
  const [historyItems, setHistoryItems] = useState<AnalysisHistoryItem[]>([])
  const [historyBusy, setHistoryBusy] = useState(false)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [fileDetail, setFileDetail] = useState<FileDetail | null>(null)
  const [fileDetailBusy, setFileDetailBusy] = useState(false)
  const [fileDetailError, setFileDetailError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [llmConfiguration, setLlmConfiguration] = useState<LlmConfiguration | null>(null)
  const [llmProviders, setLlmProviders] = useState<readonly LlmProvider[]>([])
  const [llmLoading, setLlmLoading] = useState(true)
  const [llmError, setLlmError] = useState<string | null>(null)
  const [fixConfiguration, setFixConfiguration] = useState<FixConfiguration>({ rules: '' })
  const [fixLoading, setFixLoading] = useState(true)
  const [fixError, setFixError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLlmLoading(true)
    setLlmError(null)
    void Promise.all([getLlmConfiguration(), getLlmProviders()])
      .then(([configuration, providerCatalog]) => {
        if (cancelled) return
        setLlmConfiguration(configuration)
        setLlmProviders(providerCatalog.providers)
      })
      .catch((loadError: unknown) => {
        if (!cancelled) {
          setLlmError(loadError instanceof Error ? loadError.message : 'Unable to load LLM configuration.')
        }
      })
      .finally(() => {
        if (!cancelled) setLlmLoading(false)
      })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    let cancelled = false
    if (typeof getFixConfiguration !== 'function') {
      setFixLoading(false)
      return
    }
    setFixLoading(true)
    setFixError(null)
    void getFixConfiguration()
      .then((configuration) => { if (!cancelled) setFixConfiguration(configuration) })
      .catch((loadError: unknown) => {
        if (!cancelled) setFixError(loadError instanceof Error ? loadError.message : 'Unable to load Fix rules.')
      })
      .finally(() => { if (!cancelled) setFixLoading(false) })
    return () => { cancelled = true }
  }, [])

  const refreshHistory = async () => {
    setHistoryBusy(true)
    setHistoryError(null)
    try {
      const history = await getAnalysisHistory()
      setHistoryItems(history.items)
    } catch (historyLoadError) {
      setHistoryError(historyLoadError instanceof Error ? historyLoadError.message : 'Analysis history unavailable.')
    } finally {
      setHistoryBusy(false)
    }
  }

  const refreshProjects = async () => {
    setProjectsBusy(true)
    setProjectsError(null)
    try {
      const projectCatalog = await getProjects()
      setProjects(projectCatalog.items)
    } catch (projectsLoadError) {
      setProjectsError(projectsLoadError instanceof Error ? projectsLoadError.message : 'Repositories unavailable.')
    } finally {
      setProjectsBusy(false)
    }
  }

  const refreshCatalogs = async () => {
    await Promise.all([refreshHistory(), refreshProjects()])
  }

  useEffect(() => {
    void refreshCatalogs()
  }, [])

  useEffect(() => {
    const onHashChange = () => setView(viewFromHash())
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  useEffect(() => {
    if (!analysisId || status === 'completed' || status === 'failed') return
    let cancelled = false
    const poll = async () => {
      try {
        const [nextStatus, nextSummary] = await Promise.all([
          getAnalysisStatus(analysisId),
          getAnalysisSummary(analysisId),
        ])
        if (!cancelled) {
          setStatus(nextStatus.status)
          setSummary(nextSummary.summary)
          setError(nextStatus.failure_message)
        }
      } catch (pollError) {
        if (!cancelled) setError(pollError instanceof Error ? pollError.message : 'Polling failed.')
      }
    }
    void poll()
    const timer = window.setInterval(() => void poll(), 3000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [analysisId, status])

  useEffect(() => {
    if (!analysisId || status !== 'completed') return
    const controller = new AbortController()
    setResultsBusy(true)
    setFindingsError(null)
    setHotspotsError(null)
    setFilesError(null)
    const requestOptions = { signal: controller.signal }
    const loadFindings = async () => {
      try {
        setFindings(await getAnalysisFindings(analysisId, requestOptions))
      } catch (loadError) {
        if (!controller.signal.aborted) {
          setFindingsError(loadError instanceof Error ? loadError.message : 'Findings unavailable.')
        }
      }
    }
    const loadHotspots = async () => {
      try {
        setHotspots(await getAnalysisHotspots(analysisId, 20, requestOptions))
      } catch (loadError) {
        if (!controller.signal.aborted) {
          setHotspotsError(loadError instanceof Error ? loadError.message : 'Hotspots unavailable.')
        }
      }
    }
    const loadFiles = async () => {
      try {
        setFileInsights((await getAnalysisFiles(analysisId, 100, 0, requestOptions)).items)
      } catch (loadError) {
        if (!controller.signal.aborted) {
          setFilesError(loadError instanceof Error ? loadError.message : 'File catalog unavailable.')
        }
      }
    }
    void Promise.all([loadFindings(), loadHotspots(), loadFiles()]).finally(() => {
      if (!controller.signal.aborted) setResultsBusy(false)
    })
    return () => controller.abort()
  }, [analysisId, status])

  useEffect(() => {
    if (status === 'completed' && !selectedFilePath && fileInsights.length > 0) {
      setSelectedFilePath(fileInsights[0].path)
    }
  }, [fileInsights, selectedFilePath, status])

  useEffect(() => {
    if (!analysisId || status !== 'completed' || !selectedFilePath) {
      setFileDetail(null)
      return
    }
    const controller = new AbortController()
    setFileDetailBusy(true)
    setFileDetailError(null)
    void getAnalysisFileDetail(analysisId, selectedFilePath, { signal: controller.signal })
      .then((detail) => { if (!controller.signal.aborted) setFileDetail(detail) })
      .catch((detailError) => {
        if (!controller.signal.aborted) {
          setFileDetailError(
            detailError instanceof Error ? detailError.message : 'File detail unavailable.',
          )
        }
      })
      .finally(() => { if (!controller.signal.aborted) setFileDetailBusy(false) })
    return () => controller.abort()
  }, [analysisId, selectedFilePath, status])

  const navigate = (next: View) => {
    window.location.hash = next
    setView(next)
  }

  const submitRepository = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const submittedRepositoryUrl = repositoryUrl.trim()
      const accepted = await createAnalysis(submittedRepositoryUrl)
      void refreshCatalogs()
      setAnalyzedRepositoryUrl(submittedRepositoryUrl)
      setAnalysisId(accepted.analysis_id)
      setStatus(accepted.status)
      setSummary(null)
      setFindings([])
      setHotspots([])
      setFileInsights([])
      setFindingsError(null)
      setHotspotsError(null)
      setFilesError(null)
      setSelectedFilePath(null)
      navigate('overview')
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : 'Could not queue analysis.')
    } finally {
      setBusy(false)
    }
  }

  const hasAnalysis = Boolean(analysisId)
  const activeView = useMemo(() => activeViewFor(view, hasAnalysis), [hasAnalysis, view])
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#repositories" onClick={() => setView('repositories')}>
          <span className="brand-glyph">C</span>
          <span>CodePilot</span>
        </a>
        <p className="workspace-label">Workspace / local</p>
        <nav aria-label="Primary navigation">
          {views.map((item) => (
            <button
              className={`nav-item ${activeView === item.id ? 'is-active' : ''}`}
              disabled={!hasAnalysis && !canOpenWithoutAnalysis(item.id)}
              key={item.id}
              onClick={() => navigate(item.id)}
              type="button"
            >
              <span aria-hidden="true">{item.icon}</span>
              {item.label}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <a href={apiDocsUrl} target="_blank" rel="noreferrer">API documentation -&gt;</a>
          <span className="runtime-status"><i /> API connected by request</span>
        </div>
      </aside>

      <WorkspaceView
        activeView={activeView}
        analysisId={analysisId}
        analyzedRepositoryUrl={analyzedRepositoryUrl}
        busy={busy}
        error={error}
        fileDetail={fileDetail}
        fileDetailBusy={fileDetailBusy}
        fileDetailError={fileDetailError}
        fileInsights={fileInsights}
        filesError={filesError}
        findings={findings}
        findingsError={findingsError}
        historyBusy={historyBusy}
        historyError={historyError}
        historyItems={historyItems}
        hotspots={hotspots}
        hotspotsError={hotspotsError}
        navigate={navigate}
        onDelete={async (analysisIds) => {
          const result = await deleteAnalyses(analysisIds, deleteAnalysis)
          if (analysisId && result.deleted.includes(analysisId)) {
            setAnalysisId(null)
            setAnalyzedRepositoryUrl(null)
            setStatus(null)
            setSummary(null)
            setFindings([])
            setHotspots([])
            setFileInsights([])
            setSelectedFilePath(null)
            navigate('analyses')
          }
          await refreshCatalogs()
          return result
        }}
        onRepositoryUrlChange={setRepositoryUrl}
        onSelectRun={(run) => {
          setAnalysisId(run.analysis_id)
          setAnalyzedRepositoryUrl(run.repository_url)
          setStatus('completed')
          setError(null)
          setSummary(null)
          setFindings([])
          setHotspots([])
          setFileInsights([])
          setSelectedFilePath(null)
          void getAnalysisSummary(run.analysis_id).then((result) => setSummary(result.summary)).catch(() => undefined)
          navigate('overview')
        }}
        onSelectPath={(path) => {
          setSelectedFilePath(path)
          navigate('files')
        }}
        onSubmitRepository={submitRepository}
        projects={projects}
        projectsBusy={projectsBusy}
        projectsError={projectsError}
        repositoryUrl={repositoryUrl}
        resultsBusy={resultsBusy}
        selectedFilePath={selectedFilePath}
        status={status}
        summary={summary}
        llmConfiguration={llmConfiguration}
        llmProviders={llmProviders}
        llmLoading={llmLoading}
        llmError={llmError}
        onLlmConfigurationSaved={setLlmConfiguration}
        fixConfiguration={fixConfiguration}
        fixLoading={fixLoading}
        fixError={fixError}
        onFixConfigurationSaved={setFixConfiguration}
      />
    </div>
  )
}

type WorkspaceViewProps = {
  activeView: View
  analysisId: string | null
  analyzedRepositoryUrl: string | null
  busy: boolean
  error: string | null
  fileDetail: FileDetail | null
  fileDetailBusy: boolean
  fileDetailError: string | null
  fileInsights: FileInsight[]
  filesError: string | null
  findings: AnalysisFinding[]
  findingsError: string | null
  historyBusy: boolean
  historyError: string | null
  historyItems: AnalysisHistoryItem[]
  hotspots: FileInsight[]
  hotspotsError: string | null
  navigate: (view: View) => void
  onDelete: (analysisIds: readonly string[]) => Promise<AnalysisDeletionResult>
  onRepositoryUrlChange: (value: string) => void
  onSelectPath: (path: string) => void
  onSelectRun: (run: AnalysisHistoryItem) => void
  onSubmitRepository: (event: FormEvent<HTMLFormElement>) => void | Promise<void>
  projects: readonly Project[]
  projectsBusy: boolean
  projectsError: string | null
  repositoryUrl: string
  resultsBusy: boolean
  selectedFilePath: string | null
  status: AnalysisStatus | null
  summary: AnalysisSummaryResponse['summary']
  llmConfiguration: LlmConfiguration | null
  llmProviders: readonly LlmProvider[]
  llmLoading: boolean
  llmError: string | null
  onLlmConfigurationSaved: (configuration: LlmConfiguration) => void
  fixConfiguration: FixConfiguration
  fixLoading: boolean
  fixError: string | null
  onFixConfigurationSaved: (configuration: FixConfiguration) => void
}

function WorkspaceView({
  activeView,
  analysisId,
  analyzedRepositoryUrl,
  busy,
  error,
  fileDetail,
  fileDetailBusy,
  fileDetailError,
  fileInsights,
  filesError,
  findings,
  findingsError,
  historyBusy,
  historyError,
  historyItems,
  hotspots,
  hotspotsError,
  navigate,
  onDelete,
  onRepositoryUrlChange,
  onSelectPath,
  onSelectRun,
  onSubmitRepository,
  projects,
  projectsBusy,
  projectsError,
  repositoryUrl,
  resultsBusy,
  selectedFilePath,
  status,
  summary,
  llmConfiguration,
  llmProviders,
  llmLoading,
  llmError,
  onLlmConfigurationSaved,
  fixConfiguration,
  fixLoading,
  fixError,
  onFixConfigurationSaved,
}: WorkspaceViewProps) {
  return (
    <main className="main-content">
      <header className="topbar">
        <div>
          <p className="kicker">Evidence-first code intelligence</p>
          <h1>{views.find((item) => item.id === activeView)?.label || 'Repositories'}</h1>
        </div>
        {analysisId && <span className={`status-badge status-${status}`}>{status || 'queued'}</span>}
      </header>

      {error && <div className="alert" role="alert">{error}</div>}

      <WorkspaceContent {...{
        activeView,
        analysisId,
        analyzedRepositoryUrl,
        busy,
        error,
        fileDetail,
        fileDetailBusy,
        fileDetailError,
        fileInsights,
        filesError,
        findings,
        findingsError,
        historyBusy,
        historyError,
        historyItems,
        hotspots,
        hotspotsError,
        navigate,
        onDelete,
        onRepositoryUrlChange,
        onSelectPath,
        onSelectRun,
        onSubmitRepository,
        projects,
        projectsBusy,
        projectsError,
        repositoryUrl,
        resultsBusy,
        selectedFilePath,
        status,
        summary,
        llmConfiguration,
        llmProviders,
        llmLoading,
        llmError,
        onLlmConfigurationSaved,
        fixConfiguration,
        fixLoading,
        fixError,
        onFixConfigurationSaved,
      }} />
    </main>
  )
}

function SetupView({
  configuration,
  providers,
  loading,
  loadError,
  onSaved,
  fixConfiguration,
  fixLoading,
  fixError,
  onFixSaved,
}: {
  configuration: LlmConfiguration | null
  providers: readonly LlmProvider[]
  loading: boolean
  loadError: string | null
  onSaved: (configuration: LlmConfiguration) => void
  fixConfiguration: FixConfiguration
  fixLoading: boolean
  fixError: string | null
  onFixSaved: (configuration: FixConfiguration) => void
}) {
  const [enabled, setEnabled] = useState(false)
  const [provider, setProvider] = useState('openai')
  const [model, setModel] = useState('')
  const [reasoningEffort, setReasoningEffort] = useState<string | null>(null)
  const [apiKey, setApiKey] = useState('')
  const [message, setMessage] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [fixRules, setFixRules] = useState('')
  const [fixSaving, setFixSaving] = useState(false)
  const [fixMessage, setFixMessage] = useState<string | null>(null)
  useEffect(() => {
    if (!configuration) return
    setEnabled(configuration.enabled)
    setProvider(configuration.provider)
    setModel(configuration.model)
    setReasoningEffort(configuration.reasoning_effort ?? null)
    setApiKey('')
  }, [configuration])
  useEffect(() => setFixRules(fixConfiguration.rules), [fixConfiguration.rules])
  const models = configuration?.provider === provider ? (configuration.available_models ?? []) : []
  const reasoningEfforts = configuration?.provider === provider
    ? (configuration.reasoning_efforts_by_model?.[model] ?? [])
    : []
  async function save() {
    if (loading || !configuration) return
    setSaving(true); setMessage(null)
    try {
      const value = await saveLlmConfiguration({ enabled, provider, model: model || undefined, api_key: apiKey || undefined, ...(reasoningEffort ? { reasoning_effort: reasoningEffort } : {}) })
      onSaved(value)
      setModel(value.model); setReasoningEffort(value.reasoning_effort ?? null); setApiKey(''); setMessage('LLM configuration saved.')
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Unable to save LLM configuration.') } finally { setSaving(false) }
  }
  async function saveFixRules() {
    if (fixLoading) return
    setFixSaving(true); setFixMessage(null)
    try {
      const value = await saveFixConfiguration({ rules: fixRules })
      onFixSaved(value)
      setFixMessage('Fix rules saved.')
    } catch (error) {
      setFixMessage(error instanceof Error ? error.message : 'Unable to save Fix rules.')
    } finally { setFixSaving(false) }
  }
  return <section className="page-grid"><div className="panel setup-panel"><div className="panel-title"><span>Setup</span><span className="muted">Workspace configuration</span></div>
    <form className="quality-policy-form setup-form" onSubmit={(event) => { event.preventDefault(); void save() }}>
      <label className="form-checkbox" htmlFor="setup-enabled"><input checked={enabled} disabled={loading} id="setup-enabled" onChange={(event) => setEnabled(event.target.checked)} type="checkbox" /> Enable LLM enrichment</label>
      <fieldset className="setup-fieldset" disabled={!enabled || loading}><legend>LLM enrichment</legend>
        <div className="setup-fields">
          <div className="form-field">
            <label htmlFor="setup-provider">Provider</label>
            <select id="setup-provider" value={provider} onChange={(event) => { setProvider(event.target.value); setModel(''); setReasoningEffort(null); setApiKey('') }}>{providers.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select>
          </div>
          <div className="form-field">
            <label htmlFor="setup-model">Model</label>
            <select disabled={!models.length || saving} id="setup-model" value={model} onChange={(event) => { const nextModel = event.target.value; const nextEfforts = configuration?.reasoning_efforts_by_model?.[nextModel] ?? []; setModel(nextModel); setReasoningEffort(nextEfforts.includes(reasoningEffort ?? '') ? reasoningEffort : null) }}>{models.map((item) => <option key={item} value={item}>{item}</option>)}</select>
          </div>
          <div className="form-field">
            <label htmlFor="setup-reasoning-effort">Reasoning effort</label>
            <select disabled={!model || !reasoningEfforts.length || saving} id="setup-reasoning-effort" value={reasoningEffort ?? ''} onChange={(event) => setReasoningEffort(event.target.value || null)}>
              <option value="">Provider default</option>
              {reasoningEfforts.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </div>
          <div className="form-field form-field-wide">
            <label htmlFor="setup-api-key">API key</label>
            <input id="setup-api-key" type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={configuration?.api_key_configured ? 'Stored key (leave blank to keep)' : ''} />
          </div>
        </div>
      </fieldset>
      <div className="form-actions">
        <button className="setup-submit-button" disabled={saving || loading || !configuration} type="submit">{saving ? 'Saving…' : 'Save LLM configuration'}</button>
        {(message || loadError) && <p className="muted form-message" role="status">{loadError ?? message}</p>}
      </div>
      <fieldset className="setup-fieldset fix-rules-fieldset" disabled={fixLoading || fixSaving}>
        <legend>Fix rules</legend>
        <div className="form-field">
          <label htmlFor="fix-rules">Instructions to follow when fixing findings</label>
          <textarea id="fix-rules" rows={8} value={fixRules} onChange={(event) => setFixRules(event.target.value)} />
        </div>
        <div className="form-actions">
          <button className="setup-submit-button" disabled={fixLoading || fixSaving} onClick={() => void saveFixRules()} type="button">
            {fixSaving ? 'Saving…' : 'Save Fix rules'}
          </button>
          {(fixMessage || fixError) && <p className="muted form-message" role="status">{fixError ?? fixMessage}</p>}
        </div>
      </fieldset>
    </form></div></section>
}

function WorkspaceContent(props: WorkspaceViewProps) {
  switch (props.activeView) {
    case 'repositories':
      return (
        <>
          <section className="page-grid">
            <div className="hero-card">
              <div>
                <p className="kicker">Start with a public repository</p>
                <h2>Make the next change with better evidence.</h2>
                <p>
                  {'Submit a Git HTTPS URL. CodePilot will clone it safely, queue an analysis, '
                    + 'and keep you close to the source.'}
                </p>
              </div>
              <form onSubmit={props.onSubmitRepository} className="repo-form">
                <label htmlFor="repository-url">Repository URL</label>
                <div className="input-row">
                  <input
                    id="repository-url"
                    onChange={(event) => props.onRepositoryUrlChange(event.target.value)}
                    placeholder="https://github.com/org/project"
                    required
                    type="url"
                    value={props.repositoryUrl}
                  />
                  <button
                    disabled={props.busy}
                    type="submit">{props.busy ? 'Queueing...' : 'Analyze repository'}</button>
                </div>
                <small>Public HTTPS Git repositories only. No credentials or repository code are executed.</small>
              </form>
            </div>
          </section>
          <RepositoriesView projects={props.projects} busy={props.projectsBusy} error={props.projectsError} />
        </>
      )
    case 'analyses':
      return (
        <HistoryView
          items={props.historyItems}
          busy={props.historyBusy}
          error={props.historyError}
          onSelectRun={props.onSelectRun}
          onDelete={props.onDelete}
        />
      )
    case 'overview':
      return <OverviewView analysisId={props.analysisId} status={props.status} summary={props.summary} />
    case 'findings':
      return (
        <FindingsView
          findings={props.findings}
          status={props.status}
          summary={props.summary}
          error={props.error || props.findingsError}
          repositoryUrl={props.analyzedRepositoryUrl}
          analysisId={props.analysisId}
          onSelectPath={props.onSelectPath}
          llmEnabled={Boolean(props.llmConfiguration?.enabled)}
        />
      )
    case 'hotspots':
      return (
        <HotspotsView
          hotspots={props.hotspots}
          status={props.status}
          error={props.hotspotsError}
          repositoryUrl={props.analyzedRepositoryUrl}
          analysisId={props.analysisId}
          onSelectPath={props.onSelectPath}
        />
      )
    case 'files':
      return (
        <FileDetailView
          detail={props.fileDetail}
          path={props.selectedFilePath}
          files={props.fileInsights}
          status={props.status}
          busy={props.fileDetailBusy || props.resultsBusy}
          error={props.fileDetailError}
          catalogError={props.filesError}
          onSelectPath={props.onSelectPath}
        />
      )
    case 'quality':
      return (
        <QualityGateView
          summary={props.summary}
          projectId={
            props.projects.find((project) => project.repository_url === props.analyzedRepositoryUrl)?.project_id ?? null
          }
          onNavigate={props.navigate}
        />
      )

    case 'setup':
      return (
        <SetupView
          configuration={props.llmConfiguration}
          providers={props.llmProviders}
          loading={props.llmLoading}
          loadError={props.llmError}
          onSaved={props.onLlmConfigurationSaved}
          fixConfiguration={props.fixConfiguration}
          fixLoading={props.fixLoading}
          fixError={props.fixError}
          onFixSaved={props.onFixConfigurationSaved}
        />
      )

  }
}

function FindingsView({
  findings,
  status,
  summary,
  error,
  repositoryUrl,
  analysisId,
  onSelectPath,
  llmEnabled,
}: {
  findings: AnalysisFinding[]
  status: AnalysisStatus | null
  summary: AnalysisSummaryResponse['summary']
  error: string | null
  repositoryUrl: string | null
  analysisId: string | null
  onSelectPath: (path: string) => void
  llmEnabled: boolean
}) {
  const [sort, setSort] = useState<FindingSort>({ column: 'severity', direction: 'desc' })
  const [visibleColumns, setVisibleColumns] = useState<FindingColumnKey[]>(() => FINDING_COLUMNS.map(({ key }) => key))
  const [filters, setFilters] = useState<FindingFilters>({ severities: [], types: [] })
  const [draftFilters, setDraftFilters] = useState<FindingFilters>({ severities: [], types: [] })
  const [filterDialogOpen, setFilterDialogOpen] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set())
  const [fixBusy, setFixBusy] = useState(false)
  const [fixJob, setFixJob] = useState<FixJob | null>(null)
  const [fixError, setFixError] = useState<string | null>(null)
  const findingIdentity = (finding: AnalysisFinding) => finding.finding_id
    ?? `${finding.analyzer}:${finding.path}:${finding.start_line}:${finding.end_line}:${finding.rule_id}`
  useEffect(() => {
    setSelectedIds((current) => {
      const valid = new Set(findings.map(findingIdentity))
      return new Set([...current].filter((id) => valid.has(id)))
    })
  }, [findings])
  const toggleFindingSelection = (finding: AnalysisFinding) => {
    const id = findingIdentity(finding)
    setSelectedIds((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else if (next.size < 10) next.add(id)
      return next
    })
  }
  const submitFixes = async () => {
    if (!analysisId || !llmEnabled || selectedIds.size === 0 || typeof createFixJob !== 'function') return
    setFixBusy(true); setFixError(null); setFixJob(null)
    try {
      const job = await createFixJob(analysisId, [...selectedIds])
      setFixJob(job)
      if (job.status === 'queued' || job.status === 'running') {
        let current = job
        for (let attempt = 0; attempt < 180; attempt += 1) {
          await new Promise((resolve) => window.setTimeout(resolve, 1000))
          if (typeof getFixJob !== 'function') break
          current = await getFixJob(job.job_id)
          setFixJob(current)
          if (current.status === 'succeeded' || current.status === 'failed') break
        }
      }
    } catch (error) {
      setFixError(error instanceof Error ? error.message : 'Unable to fix findings.')
    } finally { setFixBusy(false) }
  }
  const availableTypes = useMemo(
    () =>
      [...new Set(findings.map((finding) => categoryLabel(finding.category)))].sort((left, right) =>
        left.localeCompare(right),
      ),
    [findings],
  )

  if (status === 'failed') {
    const noAnalyzerEvidence = error === 'No compatible analyzer could execute.'
    return (
      <EmptyState
        title={noAnalyzerEvidence ? 'No analyzers ran' : 'Analysis failed'}
        description={error || 'The analysis could not be completed.'}
      />
    )
  }
  if (status !== 'completed') {
    return <EmptyState title="Findings pending" description="Findings appear after deterministic analysis completes." />
  }
  if (findings.length === 0) {
    const outcomes = summary?.analyzer_outcomes ?? []
    const genericOnly = outcomes.length > 0 && outcomes.every((item) => item.generic || item.status === 'not_requested')
    return (
      <EmptyState
        title="0 findings; analysis completed successfully"
        description={
          genericOnly
            ? 'Only generic analyzers ran; no language-specific analyzer was applicable.'
            : 'No deterministic analyzer reported a finding.'
        }
      />
    )
  }
  const exportFindings = () => {
    if (!repositoryUrl || !analysisId) return
    const file = createFindingsMarkdownExport({
      repositoryUrl,
      analysisId,
      findings: orderedFindings,
      totalFindings: findings.length,
      filters,
      sort,
      exportedAt: new Date(),
    })
    downloadMarkdownFile(file)
  }
  const filteredFindings = filterFindings(findings, filters)
  const counts = severityCounts(filteredFindings)
  const orderedFindings = sortFindings(filteredFindings, sort)
  const canFix = llmEnabled && selectedIds.size > 0 && !fixBusy
  const toggleSort = (column: FindingColumnKey) => setSort((current) => toggleFindingSort(current, column))
  const toggleSeverity = (severity: (typeof FINDING_SEVERITIES)[number]) => {
    setDraftFilters((current) => ({
      ...current,
      severities: current.severities.includes(severity)
        ? current.severities.filter((item) => item !== severity)
        : [...current.severities, severity],
    }))
  }
  const toggleType = (type: string) => {
    setDraftFilters((current) => ({
      ...current,
      types: current.types.includes(type)
        ? current.types.filter((item) => item !== type)
        : [...current.types, type],
    }))
  }
  const openFilterDialog = () => {
    setDraftFilters({ severities: [...filters.severities], types: [...filters.types] })
    setFilterDialogOpen(true)
  }
  const applyFilters = () => {
    setFilters({ severities: [...draftFilters.severities], types: [...draftFilters.types] })
    setFilterDialogOpen(false)
  }
  const clearDraftFilters = () => setDraftFilters({ severities: [], types: [] })
  const toggleColumn = (column: FindingColumnKey) => {
    const next = visibleColumns.includes(column)
      ? visibleColumns.filter((key) => key !== column)
      : [...visibleColumns, column]
    setVisibleColumns(next)
    setSort((current) => reconcileFindingSort(current, next))
  }
  return (
    <section className="page-grid">
      <div className="finding-summary" aria-label="Finding severity summary">
        {FINDING_SEVERITIES.map((severity) => (
          <div className={`finding-summary-card severity-${severity}`} key={severity}>
            <span>{severity}</span>
            <strong>{counts[severity]}</strong>
          </div>
        ))}
      </div>
      <div className="panel table-panel">
        <div className="panel-title">
          <span>Findings ({findings.length})</span>
          <div className="table-actions">
            <button className="secondary-button" onClick={openFilterDialog} type="button">Filter</button>
            <details className="column-picker">
              <summary>Columns</summary>
              <fieldset>
                <legend className="sr-only">Choose visible columns</legend>
                {FINDING_COLUMNS.map(({ key, label }) => (
                  <label key={key}>
                    <input checked={visibleColumns.includes(key)} onChange={() => toggleColumn(key)} type="checkbox" />
                    {label}
                  </label>
                ))}
              </fieldset>
            </details>
            <button
              className="setup-submit-button"
              disabled={!canFix}
              onClick={() => void submitFixes()}
              type="button"
            >
              {fixBusy ? 'Fixing…' : 'Fix Findings'}
            </button>
            <button
              className="secondary-button"
              disabled={orderedFindings.length === 0}
              onClick={exportFindings}
              type="button"
            >
              Export findings (.md)
            </button>
          </div>
        </div>
        {(fixError || fixJob) && (
          <p className={fixError || fixJob?.status === 'failed' ? 'error-copy' : 'muted'} role="status">
            {fixError || fixJob?.error_message || (fixJob?.status === 'succeeded' && fixJob.pull_request_url
              ? <><a href={fixJob.pull_request_url} rel="noreferrer" target="_blank">Pull Request ready</a></>
              : `Fix job ${fixJob?.status}.`)}
          </p>
        )}
        <AppliedFilterTags values={[...filters.severities, ...filters.types]} />
        <TableFilterDialog
          onApply={applyFilters}
          onCancel={() => setFilterDialogOpen(false)}
          open={filterDialogOpen}
          title="Filter findings"
        >
          <fieldset className="filter-dialog-group">
            <legend>Severity</legend>
            {FINDING_SEVERITIES.map((severity) => (
              <label key={severity}>
                <input
                  checked={draftFilters.severities.includes(severity)}
                  onChange={() => toggleSeverity(severity)}
                  type="checkbox"
                />
                {severity.charAt(0).toUpperCase() + severity.slice(1)}
              </label>
            ))}
          </fieldset>
          <fieldset className="filter-dialog-group">
            <legend>Type</legend>
            {availableTypes.map((type) => (
              <label key={type}>
                <input checked={draftFilters.types.includes(type)} onChange={() => toggleType(type)} type="checkbox" />
                {type}
              </label>
            ))}
          </fieldset>
          <button
            className="filter-reset-button"
            disabled={draftFilters.severities.length === 0 && draftFilters.types.length === 0}
            onClick={clearDraftFilters}
            type="button"
          >
            Clear filters
          </button>
        </TableFilterDialog>
        {filteredFindings.length === 0 ? (
          <EmptyState
            title="No findings match the selected filters."
            description="Clear one or more filters to show findings again."
            compact
          />
        ) : visibleColumns.length === 0 ? (
          <EmptyState
            title="No columns visible"
            description="Use the Columns menu above to show at least one finding column."
            compact
          />
        ) : (
          <div className="findings-table-wrap">
            <table className="findings-table">
              <caption className="sr-only">Repository findings sorted by {sort.column}</caption>
              <thead>
                <tr>
                  <th aria-label="Select" scope="col" />
                  {FINDING_COLUMNS.filter(({ key }) => visibleColumns.includes(key)).map(({ key, label }) => (
                    <th
                      aria-sort={sort.column === key ? (sort.direction === 'asc' ? 'ascending' : 'descending') : 'none'}
                      key={key}
                      scope="col"
                    >
                      <button className="table-sort-button" onClick={() => toggleSort(key)} type="button">
                        {label}
                        {sort.column === key && (
                          <span aria-hidden="true" className="sort-indicator">
                            {sort.direction === 'asc' ? 'asc' : 'desc'}
                          </span>
                        )}
                      </button>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {orderedFindings.map((finding) => {
                  const severity = displaySeverity(finding.severity)
                  const findingLocation = [
                    `${finding.path}:${finding.start_line}`,
                    finding.end_line !== finding.start_line ? `-${finding.end_line}` : '',
                  ].join('')
                  return (
                    <tr key={`${finding.analyzer}-${finding.path}-${finding.start_line}-${finding.rule_id}`}>
                      <td className="finding-select-cell">
                        <input
                          aria-label={`Select finding ${finding.rule_id} at ${finding.path}:${finding.start_line}`}
                          checked={selectedIds.has(findingIdentity(finding))}
                          disabled={!selectedIds.has(findingIdentity(finding)) && selectedIds.size >= 10}
                          onChange={() => toggleFindingSelection(finding)}
                          type="checkbox"
                        />
                      </td>
                      {visibleColumns.includes('description') && <td data-label="Description">
                        <strong>{finding.message}</strong>
                        <small className="finding-meta">
                          <button
                            className="path-link"
                            onClick={() => onSelectPath(finding.path)}
                            type="button"
                          >
                            <code>{findingLocation}</code>
                          </button>

                          <span>{finding.rule_id} · {finding.analyzer}</span>

                        </small>
                      </td>}
                      {visibleColumns.includes('severity') && (
                        <td data-label="Severity">
                          <span className={`severity-badge severity-${severity}`}>{severity}</span>
                        </td>
                      )}
                      {visibleColumns.includes('type') && (
                        <td data-label="Type">
                          <span className="category-badge">{categoryLabel(finding.category)}</span>
                        </td>
                      )}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  )
}

function OverviewView({
  analysisId,
  status,
  summary,
}: {
  analysisId: string | null
  status: AnalysisStatus | null
  summary: AnalysisSummaryResponse['summary']
}) {
  const [enrichment, setEnrichment] = useState<EnrichmentResponse | null>(null)
  const [enrichmentBusy, setEnrichmentBusy] = useState(false)
  const [enrichmentError, setEnrichmentError] = useState<string | null>(null)
  const severityTotal = summary
    ? Object.values(summary.finding_count_by_severity).reduce((total, value) => total + value, 0)
    : null
  const risk = summary?.risk_assessment
  const cards = [
    [
      'Risk score',

      risk ? `${risk.score.toFixed(2)} (${risk.category})` : '—',

      risk ? `Version ${risk.version}` : 'Risk model data unavailable',
    ],

    ['Findings', severityTotal === null ? '—' : String(severityTotal), 'From completed analyzer output'],
    ['Files analyzed', summary ? String(summary.analyzed_file_count) : '—', 'Repository evidence'],
    ['Duration', summary ? `${summary.duration_seconds.toFixed(1)}s` : '—', 'Worker execution time'],

  ]
  const explain = async () => {
    if (!analysisId) return
    setEnrichmentBusy(true)
    setEnrichmentError(null)
    try {
      setEnrichment(await requestEnrichment(analysisId, 'deterministic-summary'))
    } catch (requestError) {
      setEnrichmentError(requestError instanceof Error ? requestError.message : 'AI enrichment failed.')
    } finally {
      setEnrichmentBusy(false)
    }
  }
  return (
    <section className="page-grid">
      <div className="section-heading">
        <div>
          <p className="kicker">Analysis overview</p>
          <h2>{analysisId ? `Run ${analysisId.slice(0, 8)}` : 'No active analysis'}</h2>
        </div>
        <span className={`status-badge status-${status}`}>{status || 'idle'}</span>
      </div>
      <div className="metric-grid">
        {cards.map(([label, value, note]) => (
          <article className="metric-card" key={label}>
            <span>{label}</span>
            <strong>{value}</strong>
            <small>{note}</small>
          </article>
        ))}
      </div>
      <div className="panel">
        <div className="panel-title">
          <span>Findings by severity</span>
          <span className="muted">Reported by the API</span>
        </div>
        {summary ? (
          Object.entries(summary.finding_count_by_severity).map(([severity, count]) => (
            <div className="availability-row" key={severity}>
              <span>{severity}</span>
              <strong>{count}</strong>
            </div>
          ))
        ) : (
          <EmptyState
            title="Severity data pending"
            description="Completed analyzer output will populate this breakdown."
            compact
          />
        )}
      </div>
      <div className="panel">
        <div className="panel-title">
          <span>Analyzer outcomes</span>
          <span className="muted">Worker evidence</span>
        </div>
        {summary?.analyzer_outcomes?.length ? (
          summary.analyzer_outcomes.map((item) => (
            <div className="availability-row" key={item.analyzer}>
              <span>{item.analyzer}</span>
              <span className={`availability-${item.status}`}>{item.status}</span>
              <small>{item.tool}</small>
            </div>
          ))
        ) : (
          <EmptyState
            title="Analyzer evidence pending"
            description="Completed analyzer output will populate this list."
            compact
          />
        )}
      </div>
      <div className="panel">
        <div className="panel-title">
          <span>Optional AI explanation</span>
          <span className="muted">Always grounded in stored evidence</span>
        </div>
        <button
          className="secondary-button"
          disabled={!summary || enrichmentBusy}
          onClick={() => void explain()}
          type="button"
        >
          {enrichmentBusy ? 'Generating...' : 'Explain deterministic summary'}
        </button>
        {enrichmentError && <p className="error-copy" role="alert">{enrichmentError}</p>}
        {enrichment && (
          <div className="ai-result">
            <strong>
              {enrichment.ai_generated ? 'AI-generated explanation' : 'AI enrichment disabled'}
            </strong>
            {enrichment.text && <p>{enrichment.text}</p>}
            {enrichment.citations.length > 0 && (
              <small>Citations: {enrichment.citations.join(', ')}</small>
            )}
          </div>
        )}
      </div>
    </section>
  )
}

function HistoryView({
  items,
  busy,
  error,
  onSelectRun,
  onDelete,
}: {
  items: AnalysisHistoryItem[]
  busy: boolean
  error: string | null
  onSelectRun: (run: AnalysisHistoryItem) => void
  onDelete: (analysisIds: readonly string[]) => Promise<AnalysisDeletionResult>
}) {
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set())
  const [confirmationIds, setConfirmationIds] = useState<string[] | null>(null)
  const [deleteBusy, setDeleteBusy] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const visibleIds = items.map((item) => item.analysis_id)
  const selectionState = getSelectionState(selectedIds, visibleIds)

  useEffect(() => {
    setSelectedIds((current) => new Set([...current].filter((id) => visibleIds.includes(id))))
  }, [items])

  const select = (run: AnalysisHistoryItem) => onSelectRun(run)
  const openDelete = (analysisIds: readonly string[]) => {
    setDeleteError(null)
    setConfirmationIds([...analysisIds])
  }
  const confirmDelete = async () => {
    if (!confirmationIds?.length) return
    setDeleteBusy(true)
    setDeleteError(null)
    try {
      const result = await onDelete(confirmationIds)
      setSelectedIds((current) => {
        const next = new Set(current)
        result.deleted.forEach((id) => next.delete(id))
        return next
      })
      if (result.failed.length > 0) {
        setDeleteError(
          `${result.failed.length} analysis${result.failed.length === 1 ? '' : 'es'} could not be deleted.`,
        )
      }
      setConfirmationIds(null)
    } catch (deleteError) {
      setDeleteError(deleteError instanceof Error ? deleteError.message : 'Analysis could not be deleted.')
    } finally {
      setDeleteBusy(false)
    }
  }
  return (
    <section className="page-grid">
      <div className="panel table-panel">
        <div className="panel-title">
          <span>Analysis history</span>
          <div className="table-actions">
            <span className="muted">Latest first</span>
            <button
              className="danger-button"
              disabled={selectedIds.size === 0 || deleteBusy}
              onClick={() => openDelete([...selectedIds])}
              type="button"
            >
              Delete selected ({selectedIds.size})
            </button>
          </div>
        </div>
        {error && <p className="error-copy" role="alert">{error}</p>}
        {deleteError && <p className="error-copy" role="alert">{deleteError}</p>}
        {busy ? (
          <EmptyState title="Loading history" description="Reading completed analyses." compact />
        ) : items.length ? (
          <div className="history-table-wrap">
            <table className="history-table">
              <caption className="sr-only">Completed repository analyses</caption>
              <thead>
                <tr>
                  <th className="history-select-cell" scope="col">
                    <label>
                      <span className="sr-only">Select all analyses</span>
                      <input
                        aria-label="Select all analyses"
                        checked={selectionState.checked}
                        ref={(element) => {
                          if (element) element.indeterminate = selectionState.indeterminate
                        }}
                        onChange={(event) =>
                          setSelectedIds((current) =>
                            toggleAllHistorySelection(current, visibleIds, event.target.checked),
                          )
                        }
                        type="checkbox"
                      />
                    </label>
                  </th>
                  <th scope="col">Repository</th>
                  <th scope="col">Risk</th>
                  <th scope="col">Findings</th>
                  <th scope="col">Files</th>
                  <th scope="col">Duration</th>
                  <th scope="col">Date</th>
                  <th scope="col">Actions</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr
                    className="history-table-row"
                    key={item.analysis_id}
                    onClick={() => select(item)}
                    onKeyDown={(event) => {
                      if (isHistoryActivationKey(event.key)) {
                        event.preventDefault()
                        select(item)
                      }
                    }}
                    tabIndex={0}
                  >
                    <td
                      className="history-select-cell"
                      onClick={(event) => event.stopPropagation()}
                    >
                      <input
                        aria-label={`Select analysis ${item.repository_name}`}
                        checked={selectedIds.has(item.analysis_id)}
                        onChange={() =>
                          setSelectedIds((current) =>
                            toggleHistorySelection(current, item.analysis_id),
                          )
                        }
                        type="checkbox"
                      />
                    </td>
                    <th scope="row">
                      <a
                        href="#overview"
                        onClick={(event) => {
                          event.preventDefault()
                          select(item)
                        }}
                      >
                        {item.repository_name}
                      </a>
                      <code>{item.analysis_id}</code>
                    </th>
                    <td>{formatHistoryRisk(item.risk_score, item.risk_category)}</td>
                    <td>{item.finding_count}</td>
                    <td>{item.analyzed_file_count}</td>
                    <td>{item.duration_seconds.toFixed(1)}s</td>
                    <td>{formatHistoryDate(item.created_at)}</td>
                    <td>
                      <button
                        aria-label={`Delete analysis ${item.repository_name}`}
                        className="danger-button"
                        disabled={deleteBusy}
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation()
                          openDelete([item.analysis_id])
                        }}
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            title="No analyses"
            description="Submit a repository to create your first completed analysis."
            compact
          />
        )}
      </div>
      <ConfirmationDialog
        busy={deleteBusy}
        confirmLabel={confirmationIds?.length === 1 ? 'Delete analysis' : 'Delete analyses'}
        onCancel={() => {
          if (!deleteBusy) setConfirmationIds(null)
        }}
        onConfirm={() => void confirmDelete()}
        open={confirmationIds !== null}
        title={confirmationIds?.length === 1 ? 'Delete analysis?' : 'Delete selected analyses?'}
      >
        {confirmationIds?.length === 1
          ? 'This analysis and its stored evidence will be deleted. This cannot be undone.'
          : `This will permanently delete ${confirmationIds?.length ?? 0} analyses and their stored evidence. ` +
            'This cannot be undone.'}
      </ConfirmationDialog>
    </section>
  )
}

function HotspotsView({
  hotspots,
  status,
  error,
  repositoryUrl,
  analysisId,
  onSelectPath,
}: {
  hotspots: FileInsight[]
  status: AnalysisStatus | null
  error: string | null
  repositoryUrl: string | null
  analysisId: string | null
  onSelectPath: (path: string) => void
}) {
  const [sort, setSort] = useState<HotspotSort>({ column: 'hotspot_score', direction: 'desc' })
  const [filters, setFilters] = useState<HotspotFilters>({ risks: [] })
  const [draftFilters, setDraftFilters] = useState<HotspotFilters>({ risks: [] })
  const [filterDialogOpen, setFilterDialogOpen] = useState(false)
  const [exportBusy, setExportBusy] = useState(false)
  const filteredHotspots = useMemo(() => filterHotspots(hotspots, filters), [filters, hotspots])
  const orderedHotspots = useMemo(() => sortHotspots(filteredHotspots, sort), [filteredHotspots, sort])
  const toggleRisk = (risk: (typeof HOTSPOT_RISKS)[number]) => {
    setDraftFilters((current) => ({
      risks: current.risks.includes(risk) ? current.risks.filter((item) => item !== risk) : [...current.risks, risk],
    }))
  }
  const openFilterDialog = () => {
    setDraftFilters({ risks: [...filters.risks] })
    setFilterDialogOpen(true)
  }
  const applyFilters = () => {
    setFilters({ risks: [...draftFilters.risks] })
    setFilterDialogOpen(false)
  }
  const exportHotspots = async () => {
    if (!repositoryUrl || !analysisId || orderedHotspots.length === 0) return
    setExportBusy(true)
    try {
      // API returns at most 20 rows; retain an explicit cap so export detail fan-out stays bounded.
      const exportRows = orderedHotspots.slice(0, MAX_HOTSPOTS_EXPORT)
      const detailEntries = await Promise.all(exportRows.map(async (hotspot) => {
        try {
          const detail = await getAnalysisFileDetail(analysisId, hotspot.path)
          return [hotspot.path, detail] as const
        } catch {
          return [hotspot.path, null] as const
        }
      }))
      const file = createHotspotsMarkdownExport({
        repositoryUrl,
        analysisId,
        hotspots: exportRows,
        totalHotspotsLoaded: hotspots.length,
        filters,
        sort,
        details: Object.fromEntries(detailEntries),
        exportedAt: new Date(),
      })
      downloadMarkdownFile(file)
    } finally {
      setExportBusy(false)
    }
  }
  if (status !== 'completed') {
    return <EmptyState title="Hotspots pending" description="Hotspots appear after deterministic analysis completes." />
  }
  if (error && hotspots.length === 0) return <EmptyState title="Hotspots unavailable" description={error} />
  if (hotspots.length === 0) {
    return <EmptyState title="No hotspots" description="No file reached the configured hotspot threshold." />
  }
  const hotspotCountLabel = filteredHotspots.length === hotspots.length
    ? hotspots.length
    : `${filteredHotspots.length} of ${hotspots.length}`
  const sortLabel = HOTSPOT_COLUMNS.find(({ key }) => key === sort.column)?.label ?? sort.column
  return (
    <section id="hotspots" className="page-grid">
      <div className="panel table-panel">
        <div className="panel-title">
          <span>
            Hotspots ({hotspotCountLabel})
          </span>
          <div className="table-actions">
            <button className="secondary-button" onClick={openFilterDialog} type="button">Filter</button>
            <button
              className="secondary-button"
              disabled={orderedHotspots.length === 0 || exportBusy}
              onClick={() => void exportHotspots()}
              type="button"
            >
              {exportBusy ? 'Exporting...' : 'Export hotspots (.md)'}
            </button>
          </div>
        </div>
        <AppliedFilterTags values={filters.risks} />
        <TableFilterDialog
          onApply={applyFilters}
          onCancel={() => setFilterDialogOpen(false)}
          open={filterDialogOpen}
          title="Filter hotspots"
        >
          <fieldset className="filter-dialog-group">
            <legend>Risk</legend>
            {HOTSPOT_RISKS.map((risk) => (
              <label key={risk}>
                <input checked={draftFilters.risks.includes(risk)} onChange={() => toggleRisk(risk)} type="checkbox" />
                {risk.charAt(0).toUpperCase() + risk.slice(1)}
              </label>
            ))}
          </fieldset>
          <button
            className="filter-reset-button"
            disabled={draftFilters.risks.length === 0}
            onClick={() => setDraftFilters({ risks: [] })}
            type="button"
          >
            Clear filters
          </button>
        </TableFilterDialog>
        {filteredHotspots.length === 0 ? (
          <EmptyState
            title="No hotspots match the selected filters."
            description="Clear the risk filter to show hotspots again."
            compact
          />
        ) : (
          <div className="findings-table-wrap">
            <table className="findings-table">
              <caption className="sr-only">Hotspots sorted by {sortLabel}</caption>
              <thead>
                <tr>
                  {HOTSPOT_COLUMNS.map(({ key, label }) => (
                    <th
                      aria-sort={sort.column === key ? (sort.direction === 'asc' ? 'ascending' : 'descending') : 'none'}
                      key={key}
                      scope="col"
                    >
                      <button
                        className="table-sort-button"
                        onClick={() =>
                          setSort((current) => toggleHotspotSort(current, key as HotspotColumnKey))
                        }
                        type="button"
                      >
                        {label}
                        {sort.column === key && (
                          <span aria-hidden="true" className="sort-indicator">
                            {sort.direction === 'asc' ? 'asc' : 'desc'}
                          </span>
                        )}
                      </button>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {orderedHotspots.map((hotspot) => (
                  <tr key={hotspot.path}>
                    <td>
                      <button
                        className="path-link"
                        onClick={() => onSelectPath(hotspot.path)}
                        type="button"
                      >
                        <code>{hotspot.path}</code>
                      </button>
                    </td>
                    <td>{hotspot.hotspot_score.toFixed(2)}</td>
                    <td>
                      {hotspot.risk
                        ? `${hotspot.risk.score.toFixed(2)} (${hotspotRisk(hotspot)})`
                        : 'Unavailable'}
                    </td>
                    <td>{formatHotspotComponents(hotspot)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  )
}

function findingDisclosureKey(path: string, finding: AnalysisFinding, index: number): string {
  return `${path}-${finding.analyzer}-${finding.rule_id}-${finding.start_line}-${finding.end_line}-${index}`
}

function FindingDetailCard({
  finding,
  expanded,
  onToggle,
}: {
  finding: AnalysisFinding
  expanded: boolean
  onToggle: () => void
}) {
  const sourceId = useId()
  const summary = (
    <>
      <span>
        <strong>{finding.title || finding.rule_id}</strong><br />
        {finding.message}<br />
        <small>

          Lines {finding.start_line}-{finding.end_line} · {finding.analyzer}
          {finding.source_context ? ` · ${expanded ? 'Hide code' : 'View code'}` : ''}

        </small>
      </span>
      <span className={`severity-badge severity-${finding.severity}`}>{finding.severity}</span>
    </>
  )
  return (
    <article className="finding-detail">
      {finding.source_context ? (
        <button
          aria-controls={sourceId}
          aria-expanded={expanded}
          className="availability-row finding-disclosure"
          onClick={onToggle}
          type="button"
        >
          {summary}
        </button>
      ) : (
        <div className="availability-row">{summary}</div>
      )}
      {expanded && finding.source_context && (
        <div
          className="source-context"
          id={sourceId}
          aria-label={`Source context for lines ${finding.start_line}-${finding.end_line}`}
        >
          {finding.source_context.lines.map((line) => (
            <div
              className={`source-line ${
                line.highlighted ||
                (line.number >= finding.start_line && line.number <= finding.end_line)
                  ? 'source-line-highlight'
                  : ''}`}
              key={line.number}
            >
              <span className="source-line-number">{line.number}</span>
              <code>{line.text || ' '}</code>
            </div>
          ))}
        </div>
      )}
      <div className="finding-meta">
        <div><strong>Evidence</strong><p>{finding.evidence || 'Evidence unavailable.'}</p></div>
        <div>
          <strong>Remediation</strong>
          <p>{finding.remediation || 'No remediation was provided by the analyzer.'}</p>
        </div>
      </div>
    </article>
  )
}

function FileMetricGrid({ detail }: { detail: FileDetail }) {
  return (
    <div className="metric-grid">
      <article className="metric-card">
        <span>Hotspot score</span>
        <strong>{detail.hotspot_score.toFixed(2)}</strong>
        <small>History and finding evidence</small>
      </article>
      <article className="metric-card">
        <span>Risk</span>

        <strong>{detail.risk ? detail.risk.score.toFixed(2) : '—'}</strong>
        <small>{detail.risk ? `${detail.risk.category} · v${detail.risk.version}` : '—'}</small>

      </article>
      <article className="metric-card">
        <span>Findings</span>
        <strong>{detail.findings.length}</strong>
        <small>Stored analyzer evidence</small>
      </article>
    </div>
  )
}

function FileRiskComponents({ risk }: { risk: FileDetail['risk'] }) {
  return (
    <div className="panel">
      <div className="panel-title"><span>Risk components</span><span className="muted">Normalized values</span></div>
      {Object.entries(risk?.components ?? {}).map(([name, value]) => (
        <div className="availability-row" key={name}>
          <span>{name}</span>
          <strong>{value.toFixed(2)}</strong>
        </div>
      ))}
    </div>
  )
}

function FileFindingsPanel({
  detail,
  expandedFindingKey,
  onToggle,
}: {
  detail: FileDetail
  expandedFindingKey: string | null
  onToggle: (key: string) => void
}) {
  return (
    <div className="panel">
      <div className="panel-title"><span>Findings in file</span></div>
      {detail.findings.length
        ? detail.findings.map((finding, index) => {
            const findingKey = findingDisclosureKey(detail.path, finding, index)
            return (
              <FindingDetailCard
                expanded={expandedFindingKey === findingKey}
                finding={finding}
                key={findingKey}
                onToggle={() => onToggle(findingKey)}
              />
            )
          })
        : <EmptyState title="No findings" description="No finding is attached to this file." compact />}
    </div>
  )
}

function FileDetailView({
  detail,
  path,
  files,
  status,
  busy,
  error,
  catalogError,
  onSelectPath,
}: {
  detail: FileDetail | null
  path: string | null
  files: FileInsight[]
  status: AnalysisStatus | null
  busy: boolean
  error: string | null
  catalogError: string | null
  onSelectPath: (path: string) => void
}) {
  const [expandedFindingKey, setExpandedFindingKey] = useState<string | null>(null)
  useEffect(() => setExpandedFindingKey(null), [path])
  if (status !== 'completed') {
    return (
      <EmptyState
        title="File detail pending"
        description="File-level evidence appears after deterministic analysis completes."
      />
    )
  }
  if (catalogError && files.length === 0 && !path) {
    return <EmptyState title="File catalog unavailable" description={catalogError} />
  }
  if (!path && files.length === 0) {
    return (
      <EmptyState
        title="No file evidence"
        description="The completed analysis did not include file-level evidence."
      />
    )
  }
  if (busy) return <EmptyState title="Loading file detail" description={`Loading evidence for ${path}.`} />
  if (error || !detail) {
    return (
      <EmptyState
        title="File detail unavailable"
        description={error || 'No stored evidence exists for this file.'}
      />
    )
  }
  return (
    <section className="page-grid">
      <div className="panel file-picker">
        <label htmlFor="file-select">File</label>
        <select id="file-select" value={path || ''} onChange={(event) => onSelectPath(event.target.value)}>
          {files.map((file) => <option key={file.path} value={file.path}>{file.path}</option>)}
        </select>
      </div>
      <div className="section-heading">
        <div><p className="kicker">File evidence</p><h2><code>{detail.path}</code></h2></div>
        <span className="status-badge status-completed">completed</span>
      </div>
      <FileMetricGrid detail={detail} />
      <FileRiskComponents risk={detail.risk} />
      <FileFindingsPanel
        detail={detail}
        expandedFindingKey={expandedFindingKey}
        onToggle={(findingKey) => setExpandedFindingKey((current) => current === findingKey ? null : findingKey)}
      />
    </section>
  )
}

function QualityGateFailureSummary({ gate }: { gate: any }) {
  if (gate.status === 'not_configured') {
    return (
      <EmptyState
        title="Quality gate not configured"
        description="Configure at least one quality-gate threshold to evaluate this analysis."
        compact
      />
    )
  }
  if (gate.failures.length === 0) {
    return (
      <EmptyState
        title="All configured rules passed"
        description="No quality-gate failure was reported."
        compact
      />
    )
  }
  return gate.failures.map((failure: any) => (
    <div className="availability-row" key={failure.code}>
      <strong>{failure.code}</strong>
      <span>{failure.detail}</span>
    </div>
  ))
}

function QualityGateContent(props: any) {
  const {
    projectId,
    save,
    maxCritical,
    setMaxCritical,
    maxRisk,
    setMaxRisk,
    maxHotspots,
    setMaxHotspots,
    importFile,
    saveMessage,
    importMessage,
    profiles,
    setShowRisk,
    observed,
    hotspotCount,
    summary,
    gate,
    showRisk,
    onNavigate,
  } = props

  return <section className="page-grid"><div className="panel">

    <div className="panel-title">
    <span>Quality gate</span>
    <span className={`status-badge status-${gate.status === 'failed' ? 'failed' : 'completed'}`}>
      {gate.status === 'not_configured' ? 'not configured' : gate.passed ? 'passed' : 'failed'}
    </span>
    </div>
    {projectId && <form className="quality-policy-form" onSubmit={(event) => { event.preventDefault(); void save() }}>
    <div className="form-grid">
    <div className="form-field">
    <label htmlFor="max-critical">Maximum new critical findings</label>
    <input
      id="max-critical"
      type="number"
      min="0"
      value={maxCritical}
      onChange={(event) => setMaxCritical(event.target.value)}
    />
    </div>
    <div className="form-field">
    <label htmlFor="max-risk-score">Maximum risk score</label>
    <input
      id="max-risk-score"
      type="number"
      min="0"
      max="1"
      step="0.01"
      value={maxRisk}
      onChange={(event) => setMaxRisk(event.target.value)}
    />
    </div>
    <div className="form-field">
    <label htmlFor="max-hotspots">Maximum new hotspots</label>
    <input
      id="max-hotspots"
      type="number"
      min="0"
      value={maxHotspots}
      onChange={(event) => setMaxHotspots(event.target.value)}
    />
    </div>
    <div className="form-field form-field-wide">
    <label htmlFor="sonar-profile">Import SonarQube profile XML</label>
    <input
      id="sonar-profile"
      type="file"
      accept=".xml,application/xml,text/xml"
      onChange={(event) => {
        const file = event.target.files?.[0]
        if (file) void importFile(file)
      }}
    />
    </div>
    </div>
    <div className="form-actions">
    <button className="secondary-button" type="submit">Save quality gate</button>
    {saveMessage && <small className="form-message" role="status">{saveMessage}</small>}
    {importMessage && <small className="form-message" role="status">{importMessage}</small>}
    </div>
    {profiles.length > 0 && <div className="availability-row">
    <span>Loaded profiles</span>
    <strong>{profiles.reduce((total: number, profile: any) => total + profile.rules.length, 0)} rules</strong>
    <ul>
      {profiles.flatMap((profile: any) => profile.rules.map((rule: any) => (
        <li key={`${profile.language}-${rule.analyzer}-${rule.rule_id}`}>
          {profile.language}: {rule.analyzer}:{rule.rule_id}
        </li>
      )))}
    </ul>
    </div>}</form>}<div className="metric-grid">
    <article className="metric-card">
    <button className="table-sort-button" type="button" onClick={() => setShowRisk((value: boolean) => !value)}>
    <span>Risk score</span>

    <strong>{observed.risk_score === null ? '—' : observed.risk_score.toFixed(2)}</strong>

    </button>
    <small>Click for breakdown</small>
    </article>
    <article className="metric-card">
    <span>New critical findings</span>
    <strong>{observed.new_critical_findings}</strong>
    <small>
    <button type="button" onClick={() => onNavigate('findings')}>Open findings</button>
    </small>
    </article>
    <article className="metric-card">
    <span>Hotspots</span>
    <strong>{hotspotCount}</strong>
    <small>
    <button type="button" onClick={() => onNavigate('hotspots')}>Open hotspots</button>
    </small>
    </article>
    </div>
    {showRisk && summary.risk_assessment && <div className="panel">
    <div className="panel-title">
    <span>Risk score breakdown</span>
    <span className="muted">v{summary.risk_assessment.version}</span>
    </div>
    {Object.entries(summary.risk_assessment.components).map(([name, value]) => (
      <div className="availability-row" key={name}>
        <span>{name}</span>

        <strong>{Number(value).toFixed(2)} × {Number(summary.risk_assessment?.weights[name] ?? 0).toFixed(2)}</strong>

      </div>
    ))}
    <p className="muted">Score is the weighted average of normalized repository evidence components.</p>
    </div>}
    <QualityGateFailureSummary gate={gate} />
    </div>
    </section>
}

function QualityGateView({
  summary,
  projectId,
  onNavigate,
}: {
  summary: AnalysisSummaryResponse['summary']
  projectId: string | null
  onNavigate: (view: View) => void
}) {
  const gate = summary?.quality_gate ?? {
    passed: false,
    configured: false,
    status: 'not_configured' as const,
    failures: [],
    thresholds: {
      max_new_critical_findings: null,
      max_risk_score: null,
      max_new_hotspots: null,
    },
    observed: { new_critical_findings: 0, risk_score: null, new_hotspots: 0 },
  }
  const observed = gate.observed
  const [showRisk, setShowRisk] = useState(false)
  const [maxRisk, setMaxRisk] = useState(gate.thresholds.max_risk_score?.toString() ?? '')
  const [saveMessage, setSaveMessage] = useState<string | null>(null)
  const [maxCritical, setMaxCritical] = useState(gate.thresholds.max_new_critical_findings?.toString() ?? '')
  const [maxHotspots, setMaxHotspots] = useState(gate.thresholds.max_new_hotspots?.toString() ?? '')
  const [profiles, setProfiles] = useState(summary?.quality_policy?.profiles ?? [])
  const [importMessage, setImportMessage] = useState<string | null>(null)

  useEffect(() => {
    if (!projectId) return
    void getQualityPolicy(projectId).then((policy) => {
      setMaxCritical(policy.max_new_critical_findings?.toString() ?? '')
      setMaxRisk(policy.max_risk_score?.toString() ?? '')
      setMaxHotspots(policy.max_new_hotspots?.toString() ?? '')
      setProfiles(policy.profiles)
    }).catch(() => undefined)
  }, [projectId])
  if (!summary?.quality_gate) {
    return (
      <section className="page-grid">
        <div className="panel">
          <div className="panel-title">
            <span>Quality gate</span>
            <span className="muted">Evidence only</span>
          </div>
          <EmptyState
            title="Quality-gate data unavailable"
            description="The completed analysis did not include a quality-gate evaluation."
            compact
          />
        </div>
      </section>
    )
  }
  const save = async () => {
    if (!projectId) return
    await saveQualityPolicy(projectId, {
      version: 1,
      max_new_critical_findings: maxCritical ? Number(maxCritical) : null,
      max_risk_score: maxRisk ? Number(maxRisk) : null,
      max_new_hotspots: maxHotspots ? Number(maxHotspots) : null,
      profiles,
    })
    setSaveMessage('Saved for the next analysis.')
  }
  const importFile = async (file: File) => {
    if (!projectId) return
    try {
      const report = await importQualityProfile(projectId, await file.text())
      setImportMessage(`Imported ${report.mapped} rules; ${report.unsupported.length} unsupported.`)
      const policy = await getQualityPolicy(projectId)
      setProfiles(policy.profiles)
    } catch (error) {
      setImportMessage(error instanceof Error ? error.message : 'Import failed.')
    }
  }
  const hotspotCount = totalHotspots(summary.hotspot_count)
  return (
    <QualityGateContent
      projectId={projectId}
      save={save}
      maxCritical={maxCritical}
      setMaxCritical={setMaxCritical}
      maxRisk={maxRisk}
      setMaxRisk={setMaxRisk}
      maxHotspots={maxHotspots}
      setMaxHotspots={setMaxHotspots}
      importFile={importFile}
      saveMessage={saveMessage}
      importMessage={importMessage}
      profiles={profiles}
      setShowRisk={setShowRisk}
      observed={observed}
      hotspotCount={hotspotCount}
      summary={summary}
      gate={gate}
      showRisk={showRisk}
      onNavigate={onNavigate}
    />
  )
}

function EmptyState({
  title,
  description,
  compact = false,
}: {
  title: string
  description: string
  compact?: boolean
}) {
  return (
    <div className={`empty-state ${compact ? 'is-compact' : ''}`}>
      <span className="empty-mark">[ ]</span>
      <div>
        <strong>{title}</strong>
        <p>{description}</p>
      </div>
    </div>
  )
}

export default App
