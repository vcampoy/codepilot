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
  saveLlmConfiguration,
  requestEnrichment,
  type AnalysisStatus,
  type AnalysisSummaryResponse,
  type AnalysisFinding,
  type FileDetail,
  type FileInsight,
  type EnrichmentResponse,
  type Project,
  type AnalysisHistoryItem,
  type LlmConfiguration,
} from './api'
import { deleteAnalyses, type AnalysisDeletionResult } from './analysisDeletion'
import { getSelectionState, toggleAllHistorySelection, toggleHistorySelection } from './analysisHistorySelection'
import { getLlmModelOptions } from './llmModelOptions'
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

type View = 'repositories' | 'analyses' | 'overview' | 'findings' | 'hotspots' | 'files' | 'quality'

const views: { id: View; label: string; icon: string }[] = [
  { id: 'repositories', label: 'Repositories', icon: 'R' },
  { id: 'analyses', label: 'Analysis history', icon: 'A' },
  { id: 'overview', label: 'Overview', icon: 'O' },
  { id: 'findings', label: 'Findings', icon: 'F' },
  { id: 'hotspots', label: 'Hotspots', icon: 'H' },
  { id: 'files', label: 'File detail', icon: 'D' },
  { id: 'quality', label: 'Quality gate', icon: 'Q' },
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
  const [historyItems, setHistoryItems] = useState<AnalysisHistoryItem[]>([])
  const [historyBusy, setHistoryBusy] = useState(false)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [fileDetail, setFileDetail] = useState<FileDetail | null>(null)
  const [fileDetailBusy, setFileDetailBusy] = useState(false)
  const [fileDetailError, setFileDetailError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const refreshHistory = async () => {
    setHistoryBusy(true)
    setHistoryError(null)
    try {
      const [history, projectCatalog] = await Promise.all([getAnalysisHistory(), getProjects()])
      setHistoryItems(history.items)
      setProjects(projectCatalog.items)
    } catch (historyLoadError) {
      setHistoryError(historyLoadError instanceof Error ? historyLoadError.message : 'Analysis history unavailable.')
    } finally {
      setHistoryBusy(false)
    }
  }

  useEffect(() => {
    void refreshHistory()
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
      void refreshHistory()
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
  const activeView = useMemo(() => (hasAnalysis ? view : 'repositories'), [hasAnalysis, view])

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
              disabled={!hasAnalysis && item.id !== 'repositories'}
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

      <main className="main-content">
        <header className="topbar">
          <div>
            <p className="kicker">Evidence-first code intelligence</p>
            <h1>{views.find((item) => item.id === activeView)?.label || 'Repositories'}</h1>
          </div>
          {analysisId && <span className={`status-badge status-${status}`}>{status || 'queued'}</span>}
        </header>

        {error && <div className="alert" role="alert">{error}</div>}

        {activeView === 'repositories' && (
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
              <form onSubmit={submitRepository} className="repo-form">
                <label htmlFor="repository-url">Repository URL</label>
                <div className="input-row">
                  <input
                    id="repository-url"
                    onChange={(event) => setRepositoryUrl(event.target.value)}
                    placeholder="https://github.com/org/project"
                    required
                    type="url"
                    value={repositoryUrl}
                  />
                  <button disabled={busy} type="submit">{busy ? 'Queueing...' : 'Analyze repository'}</button>
                </div>
                <small>Public HTTPS Git repositories only. No credentials or repository code are executed.</small>
              </form>
            </div>
            <EmptyState title="No repositories yet" description="Your submitted repositories will appear here with their latest analysis." />
          </section>
        )}

        {activeView === 'analyses' && <HistoryView items={historyItems} busy={historyBusy} error={historyError} onSelectRun={(run) => {
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
        }} onDelete={async (analysisIds) => {
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
          await refreshHistory()
          return result
        }} />}
        {activeView === 'overview' && <OverviewView analysisId={analysisId} status={status} summary={summary} />}
        {activeView === 'findings' && (
          <FindingsView
            findings={findings}
            status={status}
            summary={summary}
            error={error || findingsError}
            repositoryUrl={analyzedRepositoryUrl}
            analysisId={analysisId}
            onSelectPath={(path) => {
              setSelectedFilePath(path)
              navigate('files')
            }}
          />
        )}
        {activeView === 'hotspots' && (
          <HotspotsView
            hotspots={hotspots}
            status={status}
            error={hotspotsError}
            repositoryUrl={analyzedRepositoryUrl}
            analysisId={analysisId}
            onSelectPath={(path) => {
              setSelectedFilePath(path)
              navigate('files')
            }}
          />
        )}
        {activeView === 'files' && <FileDetailView detail={fileDetail} path={selectedFilePath} files={fileInsights} status={status} busy={fileDetailBusy || resultsBusy} error={fileDetailError} catalogError={filesError} onSelectPath={setSelectedFilePath} />}
        {activeView === 'quality' && <QualityGateView summary={summary} projectId={projects.find((project) => project.repository_url === analyzedRepositoryUrl)?.project_id ?? null} onNavigate={navigate} />}
      </main>
    </div>
  )
}

function FindingsView({
  findings,
  status,
  summary,
  error,
  repositoryUrl,
  analysisId,
  onSelectPath,
}: {
  findings: AnalysisFinding[]
  status: AnalysisStatus | null
  summary: AnalysisSummaryResponse['summary']
  error: string | null
  repositoryUrl: string | null
  analysisId: string | null
  onSelectPath: (path: string) => void
}) {
  const [sort, setSort] = useState<FindingSort>({ column: 'severity', direction: 'desc' })
  const [visibleColumns, setVisibleColumns] = useState<FindingColumnKey[]>(() => FINDING_COLUMNS.map(({ key }) => key))
  const [filters, setFilters] = useState<FindingFilters>({ severities: [], types: [] })
  const [draftFilters, setDraftFilters] = useState<FindingFilters>({ severities: [], types: [] })
  const [filterDialogOpen, setFilterDialogOpen] = useState(false)
  const availableTypes = useMemo(
    () => [...new Set(findings.map((finding) => categoryLabel(finding.category)))].sort((left, right) => left.localeCompare(right)),
    [findings],
  )

  if (status === 'failed') {
    const noAnalyzerEvidence = error === 'No compatible analyzer could execute.'
    return <EmptyState title={noAnalyzerEvidence ? 'No analyzers ran' : 'Analysis failed'} description={error || 'The analysis could not be completed.'} />
  }
  if (status !== 'completed') return <EmptyState title="Findings pending" description="Findings appear after deterministic analysis completes." />
  if (findings.length === 0) {
    const outcomes = summary?.analyzer_outcomes ?? []
    const genericOnly = outcomes.length > 0 && outcomes.every((item) => item.generic || item.status === 'not_requested')
    return <EmptyState title="0 findings; analysis completed successfully" description={genericOnly ? 'Only generic analyzers ran; no language-specific analyzer was applicable.' : 'No deterministic analyzer reported a finding.'} />
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
              className="secondary-button"
              disabled={orderedFindings.length === 0}
              onClick={exportFindings}
              type="button"
            >
              Export findings (.md)
            </button>
          </div>
        </div>
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
                  {FINDING_COLUMNS.filter(({ key }) => visibleColumns.includes(key)).map(({ key, label }) => (
                    <th aria-sort={sort.column === key ? (sort.direction === 'asc' ? 'ascending' : 'descending') : 'none'} key={key} scope="col">
                      <button className="table-sort-button" onClick={() => toggleSort(key)} type="button">
                        {label}
                        {sort.column === key && <span aria-hidden="true" className="sort-indicator">{sort.direction === 'asc' ? 'asc' : 'desc'}</span>}
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
                      {visibleColumns.includes('severity') && <td data-label="Severity"><span className={`severity-badge severity-${severity}`}>{severity}</span></td>}
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
    ['Findings', severityTotal === null ? 'â€”' : String(severityTotal), 'From completed analyzer output'],
    ['Files analyzed', summary ? String(summary.analyzed_file_count) : 'â€”', 'Repository evidence'],
    ['Duration', summary ? `${summary.duration_seconds.toFixed(1)}s` : 'â€”', 'Worker execution time'],
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
      if (result.failed.length > 0) setDeleteError(`${result.failed.length} analysis${result.failed.length === 1 ? '' : 'es'} could not be deleted.`)
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
          : `This will permanently delete ${confirmationIds?.length ?? 0} analyses and their stored evidence. This cannot be undone.`}
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
  if (status !== 'completed') return <EmptyState title="Hotspots pending" description="Hotspots appear after deterministic analysis completes." />
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
                    <th aria-sort={sort.column === key ? (sort.direction === 'asc' ? 'ascending' : 'descending') : 'none'} key={key} scope="col">
                      <button
                        className="table-sort-button"
                        onClick={() =>
                          setSort((current) => toggleHotspotSort(current, key as HotspotColumnKey))
                        }
                        type="button"
                      >
                        {label}
                        {sort.column === key && <span aria-hidden="true" className="sort-indicator">{sort.direction === 'asc' ? 'asc' : 'desc'}</span>}
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
                    <td>{hotspot.risk ? `${hotspot.risk.score.toFixed(2)} (${hotspotRisk(hotspot)})` : 'Unavailable'}</td>
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
        <div><strong>Remediation</strong><p>{finding.remediation || 'No remediation was provided by the analyzer.'}</p></div>
      </div>
    </article>
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
  if (catalogError && files.length === 0 && !path) return <EmptyState title="File catalog unavailable" description={catalogError} />
  if (!path && files.length === 0) {
    return (
      <EmptyState
        title="No file evidence"
        description="The completed analysis did not include file-level evidence."
      />
    )
  }
  if (busy) return <EmptyState title="Loading file detail" description={`Loading evidence for ${path}.`} />
  if (error || !detail) return <EmptyState title="File detail unavailable" description={error || 'No stored evidence exists for this file.'} />
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
      <div className="metric-grid">
        <article className="metric-card"><span>Hotspot score</span><strong>{detail.hotspot_score.toFixed(2)}</strong><small>History and finding evidence</small></article>
        <article className="metric-card">
          <span>Risk</span>
          <strong>{detail.risk ? detail.risk.score.toFixed(2) : '—'}</strong>
          <small>{detail.risk ? `${detail.risk.category} · v${detail.risk.version}` : 'Unavailable'}</small>
        </article>
        <article className="metric-card"><span>Findings</span><strong>{detail.findings.length}</strong><small>Stored analyzer evidence</small></article>
      </div>
      <div className="panel">
        <div className="panel-title"><span>Risk components</span><span className="muted">Normalized values</span></div>
        {Object.entries(detail.risk?.components ?? {}).map(([name, value]) => (
          <div className="availability-row" key={name}>
            <span>{name}</span>
            <strong>{value.toFixed(2)}</strong>
          </div>
        ))}
      </div>
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
                onToggle={() => setExpandedFindingKey((current) => current === findingKey ? null : findingKey)}
              />
            )
          })
          : <EmptyState title="No findings" description="No finding is attached to this file." compact />}
      </div>
    </section>
  )
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
  const gate = summary?.quality_gate ?? { passed: false, configured: false, status: 'not_configured' as const, failures: [], thresholds: { max_new_critical_findings: null, max_risk_score: null, max_new_hotspots: null }, observed: { new_critical_findings: 0, risk_score: null, new_hotspots: 0 } }
  const observed = gate.observed
  const [showRisk, setShowRisk] = useState(false)
  const [maxRisk, setMaxRisk] = useState(gate.thresholds.max_risk_score?.toString() ?? '')
  const [saveMessage, setSaveMessage] = useState<string | null>(null)
  const [maxCritical, setMaxCritical] = useState(gate.thresholds.max_new_critical_findings?.toString() ?? '')
  const [maxHotspots, setMaxHotspots] = useState(gate.thresholds.max_new_hotspots?.toString() ?? '')
  const [profiles, setProfiles] = useState(summary?.quality_policy?.profiles ?? [])
  const [importMessage, setImportMessage] = useState<string | null>(null)
  const [llm, setLlm] = useState<LlmConfiguration | null>(null)
  const [llmProvider, setLlmProvider] = useState('openai')
  const [llmModel, setLlmModel] = useState('gpt-4o-mini')
  const [llmModelOptions, setLlmModelOptions] = useState<string[]>([])
  const [llmKey, setLlmKey] = useState('')
  const [llmEnabled, setLlmEnabled] = useState(false)
  const [llmMessage, setLlmMessage] = useState<string | null>(null)
  const [llmLoading, setLlmLoading] = useState(true)
  const [llmLoadError, setLlmLoadError] = useState<string | null>(null)
  const [llmSaving, setLlmSaving] = useState(false)
  useEffect(() => {
    let cancelled = false
    setLlmLoading(true)
    setLlmLoadError(null)
    void getLlmConfiguration().then((configuration) => {
      if (cancelled) return
      setLlm(configuration)
      setLlmProvider(configuration.provider)
      setLlmModel(configuration.model)
      setLlmModelOptions(getLlmModelOptions(configuration.provider, configuration.model))
      setLlmEnabled(configuration.enabled)
    }).catch((loadError) => {
      if (!cancelled) setLlmLoadError(loadError instanceof Error ? loadError.message : 'LLM models unavailable.')
    }).finally(() => {
      if (!cancelled) setLlmLoading(false)
    })
    return () => { cancelled = true }
  }, [])
  useEffect(() => {
    if (!projectId) return
    void getQualityPolicy(projectId).then((policy) => {
      setMaxCritical(policy.max_new_critical_findings?.toString() ?? '')
      setMaxRisk(policy.max_risk_score?.toString() ?? '')
      setMaxHotspots(policy.max_new_hotspots?.toString() ?? '')
      setProfiles(policy.profiles)
    }).catch(() => undefined)
  }, [projectId])
  if (!summary?.quality_gate) return <section className="page-grid"><div className="panel"><div className="panel-title"><span>Quality gate</span><span className="muted">Evidence only</span></div><EmptyState title="Quality-gate data unavailable" description="The completed analysis did not include a quality-gate evaluation." compact /></div></section>
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
  const saveLlm = async () => {
    if (!llmModel) return
    setLlmSaving(true)
    try {
      const configuration = await saveLlmConfiguration({
        enabled: llmEnabled,
        provider: llmProvider,
        model: llmModel,
        ...(llmKey ? { api_key: llmKey } : {}),
      })
      setLlm(configuration)
      setLlmModelOptions(getLlmModelOptions(configuration.provider, configuration.model))
      setLlmKey('')
      setLlmMessage('Saved. The API key is never shown again.')
    } catch (error) { setLlmMessage(error instanceof Error ? error.message : 'LLM configuration failed.') }
    finally { setLlmSaving(false) }
  }
  const hotspotCount = totalHotspots(summary.hotspot_count)
  const llmPanel = <div className="panel"><div className="panel-title"><span>LLM enrichment</span><span className="muted">Optional, evidence-bound</span></div><form className="quality-policy-form" onSubmit={(event) => { event.preventDefault(); void saveLlm() }}><label className="form-checkbox"><input type="checkbox" checked={llmEnabled} onChange={(event) => setLlmEnabled(event.target.checked)} /> Enable configured LLM</label><div className="form-grid"><div className="form-field"><label htmlFor="llm-provider">Provider</label><input id="llm-provider" value={llmProvider} onChange={(event) => { const provider = event.target.value; const options = getLlmModelOptions(provider, null); setLlmProvider(provider); setLlmModelOptions(options); setLlmModel(options[0] ?? '') }} /></div><div className="form-field"><label htmlFor="llm-model">Model</label><select aria-describedby={llmLoadError ? 'llm-model-error' : undefined} disabled={llmLoading || llmSaving || llmModelOptions.length === 0} id="llm-model" onChange={(event) => setLlmModel(event.target.value)} value={llmModel}><option value="">{llmLoading ? 'Loading models…' : 'Select a model'}</option>{llmModelOptions.map((model) => <option key={model} value={model}>{model}</option>)}</select>{llmLoadError && <small className="form-message" id="llm-model-error" role="alert">{llmLoadError}</small>}</div><div className="form-field form-field-wide"><label htmlFor="llm-api-key">API key {llm?.api_key_configured ? '(configured; leave blank to keep)' : ''}</label><input id="llm-api-key" type="password" value={llmKey} onChange={(event) => setLlmKey(event.target.value)} autoComplete="off" /></div></div><div className="form-actions"><button className="secondary-button" disabled={llmLoading || llmSaving || llmModelOptions.length === 0 || !llmModel} type="submit">{llmSaving ? 'Saving...' : 'Save LLM configuration'}</button>{llmMessage && <small className="form-message" role="status">{llmMessage}</small>}</div></form></div>
  return <section className="page-grid">{llmPanel}<div className="panel"><div className="panel-title"><span>Quality gate</span><span className={`status-badge status-${gate.status === 'failed' ? 'failed' : 'completed'}`}>{gate.status === 'not_configured' ? 'not configured' : gate.passed ? 'passed' : 'failed'}</span></div>{projectId && <form className="quality-policy-form" onSubmit={(event) => { event.preventDefault(); void save() }}><div className="form-grid"><div className="form-field"><label htmlFor="max-critical">Maximum new critical findings</label><input id="max-critical" type="number" min="0" value={maxCritical} onChange={(event) => setMaxCritical(event.target.value)} /></div><div className="form-field"><label htmlFor="max-risk-score">Maximum risk score</label><input id="max-risk-score" type="number" min="0" max="1" step="0.01" value={maxRisk} onChange={(event) => setMaxRisk(event.target.value)} /></div><div className="form-field"><label htmlFor="max-hotspots">Maximum new hotspots</label><input id="max-hotspots" type="number" min="0" value={maxHotspots} onChange={(event) => setMaxHotspots(event.target.value)} /></div><div className="form-field form-field-wide"><label htmlFor="sonar-profile">Import SonarQube profile XML</label><input id="sonar-profile" type="file" accept=".xml,application/xml,text/xml" onChange={(event) => { const file = event.target.files?.[0]; if (file) void importFile(file) }} /></div></div><div className="form-actions"><button className="secondary-button" type="submit">Save quality gate</button>{saveMessage && <small className="form-message" role="status">{saveMessage}</small>}{importMessage && <small className="form-message" role="status">{importMessage}</small>}</div>{profiles.length > 0 && <div className="availability-row"><span>Loaded profiles</span><strong>{profiles.reduce((total, profile) => total + profile.rules.length, 0)} rules</strong><ul>{profiles.flatMap((profile) => profile.rules.map((rule) => <li key={`${profile.language}-${rule.analyzer}-${rule.rule_id}`}>{profile.language}: {rule.analyzer}:{rule.rule_id}</li>))}</ul></div>}</form>}<div className="metric-grid"><article className="metric-card"><button className="table-sort-button" type="button" onClick={() => setShowRisk((value) => !value)}><span>Risk score</span><strong>{observed.risk_score === null ? '—' : observed.risk_score.toFixed(2)}</strong></button><small>Click for breakdown</small></article><article className="metric-card"><span>New critical findings</span><strong>{observed.new_critical_findings}</strong><small><button type="button" onClick={() => onNavigate('findings')}>Open findings</button></small></article><article className="metric-card"><span>Hotspots</span><strong>{hotspotCount}</strong><small><button type="button" onClick={() => onNavigate('hotspots')}>Open hotspots</button></small></article></div>{showRisk && summary.risk_assessment && <div className="panel"><div className="panel-title"><span>Risk score breakdown</span><span className="muted">v{summary.risk_assessment.version}</span></div>{Object.entries(summary.risk_assessment.components).map(([name, value]) => <div className="availability-row" key={name}><span>{name}</span><strong>{value.toFixed(2)} × {(summary.risk_assessment?.weights[name] ?? 0).toFixed(2)}</strong></div>)}<p className="muted">Score is the weighted average of normalized repository evidence components.</p></div>}{gate.status === 'not_configured' && <EmptyState title="Quality gate not configured" description="Configure at least one quality-gate threshold to evaluate this analysis." compact />}{gate.failures.length ? gate.failures.map((failure) => <div className="availability-row" key={failure.code}><strong>{failure.code}</strong><span>{failure.detail}</span></div>) : gate.status !== 'not_configured' && <EmptyState title="All configured rules passed" description="No quality-gate failure was reported." compact />}</div></section>
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
