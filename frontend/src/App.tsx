import { useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import {
  apiDocsUrl,
  createAnalysis,
  getAnalysisStatus,
  getAnalysisSummary,
  getAnalysisFindings,
  getAnalysisFileDetail,
  getAnalysisHotspots,
  getAnalysisFiles,
  requestEnrichment,
  type AnalysisStatus,
  type AnalysisSummaryResponse,
  type AnalysisFinding,
  type FileDetail,
  type FileInsight,
  type EnrichmentResponse,
} from './api'
import { createFindingsMarkdownExport, downloadMarkdownFile } from './findingsExport'
import { createHotspotsMarkdownExport, MAX_HOTSPOTS_EXPORT } from './hotspotsExport'
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
  const [fileDetail, setFileDetail] = useState<FileDetail | null>(null)
  const [fileDetailBusy, setFileDetailBusy] = useState(false)
  const [fileDetailError, setFileDetailError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

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
        if (!controller.signal.aborted) setFileDetailError(detailError instanceof Error ? detailError.message : 'File detail unavailable.')
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
                <p>Submit a Git HTTPS URL. CodePilot will clone it safely, queue an analysis, and keep you close to the source.</p>
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

        {activeView === 'analyses' && <HistoryView analysisId={analysisId} status={status} />}
        {activeView === 'overview' && <OverviewView analysisId={analysisId} status={status} summary={summary} />}
        {activeView === 'findings' && <FindingsView findings={findings} status={status} summary={summary} error={error || findingsError} repositoryUrl={analyzedRepositoryUrl} analysisId={analysisId} onSelectPath={(path) => { setSelectedFilePath(path); navigate('files') }} />}
        {activeView === 'hotspots' && <HotspotsView hotspots={hotspots} status={status} error={hotspotsError} repositoryUrl={analyzedRepositoryUrl} analysisId={analysisId} onSelectPath={(path) => { setSelectedFilePath(path); navigate('files') }} />}
        {activeView === 'files' && <FileDetailView detail={fileDetail} path={selectedFilePath} files={fileInsights} status={status} busy={fileDetailBusy || resultsBusy} error={fileDetailError} catalogError={filesError} onSelectPath={setSelectedFilePath} />}
        {activeView === 'quality' && <QualityGateView summary={summary} />}
      </main>
    </div>
  )
}

function FindingsView({ findings, status, summary, error, repositoryUrl, analysisId, onSelectPath }: { findings: AnalysisFinding[]; status: AnalysisStatus | null; summary: AnalysisSummaryResponse['summary']; error: string | null; repositoryUrl: string | null; analysisId: string | null; onSelectPath: (path: string) => void }) {
  const [sort, setSort] = useState<FindingSort>({ column: 'severity', direction: 'desc' })
  const [visibleColumns, setVisibleColumns] = useState<FindingColumnKey[]>(() => FINDING_COLUMNS.map(({ key }) => key))
  const [filters, setFilters] = useState<FindingFilters>({ severities: [], types: [] })
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
    setFilters((current) => ({
      ...current,
      severities: current.severities.includes(severity)
        ? current.severities.filter((item) => item !== severity)
        : [...current.severities, severity],
    }))
  }
  const toggleType = (type: string) => {
    setFilters((current) => ({
      ...current,
      types: current.types.includes(type)
        ? current.types.filter((item) => item !== type)
        : [...current.types, type],
    }))
  }
  const clearFilters = () => setFilters({ severities: [], types: [] })
  const toggleColumn = (column: FindingColumnKey) => {
    const next = visibleColumns.includes(column) ? visibleColumns.filter((key) => key !== column) : [...visibleColumns, column]
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
            <fieldset className="finding-filter-group">
              <legend>Severity</legend>
              {FINDING_SEVERITIES.map((severity) => (
                <label key={severity}>
                  <input
                    checked={filters.severities.includes(severity)}
                    onChange={() => toggleSeverity(severity)}
                    type="checkbox"
                  />
                  {severity.charAt(0).toUpperCase() + severity.slice(1)}
                </label>
              ))}
            </fieldset>
            <fieldset className="finding-filter-group">
              <legend>Type</legend>
              {availableTypes.map((type) => (
                <label key={type}>
                  <input checked={filters.types.includes(type)} onChange={() => toggleType(type)} type="checkbox" />
                  {type}
                </label>
              ))}
            </fieldset>
            {(filters.severities.length > 0 || filters.types.length > 0) && (
              <button className="secondary-button" onClick={clearFilters} type="button">Clear filters</button>
            )}
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
        {filteredFindings.length === 0 ? (
          <EmptyState title="No findings match the selected filters." description="Clear one or more filters to show findings again." compact />
        ) : visibleColumns.length === 0 ? (
          <EmptyState title="No columns visible" description="Use the Columns menu above to show at least one finding column." compact />
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
                        {sort.column === key && <span aria-hidden="true" className="sort-indicator">{sort.direction === 'asc' ? '↑' : '↓'}</span>}
                      </button>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {orderedFindings.map((finding) => {
                  const severity = displaySeverity(finding.severity)
                  return (
                    <tr key={`${finding.analyzer}-${finding.path}-${finding.start_line}-${finding.rule_id}`}>
                      {visibleColumns.includes('description') && <td data-label="Description">
                        <strong>{finding.message}</strong>
                        <small className="finding-meta">
                          <button className="path-link" onClick={() => onSelectPath(finding.path)} type="button"><code>{finding.path}:{finding.start_line}{finding.end_line !== finding.start_line ? `-${finding.end_line}` : ''}</code></button>
                          <span>{finding.rule_id} · {finding.analyzer}</span>
                        </small>
                      </td>}
                      {visibleColumns.includes('severity') && <td data-label="Severity"><span className={`severity-badge severity-${severity}`}>{severity}</span></td>}
                      {visibleColumns.includes('type') && <td data-label="Type"><span className="category-badge">{categoryLabel(finding.category)}</span></td>}
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

function OverviewView({ analysisId, status, summary }: { analysisId: string | null; status: AnalysisStatus | null; summary: AnalysisSummaryResponse['summary'] }) {
  const [enrichment, setEnrichment] = useState<EnrichmentResponse | null>(null)
  const [enrichmentBusy, setEnrichmentBusy] = useState(false)
  const [enrichmentError, setEnrichmentError] = useState<string | null>(null)
  const severityTotal = summary ? Object.values(summary.finding_count_by_severity).reduce((total, value) => total + value, 0) : null
  const risk = summary?.risk_assessment
  const cards = [
    ['Risk score', risk ? `${risk.score.toFixed(2)} (${risk.category})` : '—', risk ? `Version ${risk.version}` : 'Risk model data unavailable'],
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
  return <section className="page-grid"><div className="section-heading"><div><p className="kicker">Analysis overview</p><h2>{analysisId ? `Run ${analysisId.slice(0, 8)}` : 'No active analysis'}</h2></div><span className={`status-badge status-${status}`}>{status || 'idle'}</span></div><div className="metric-grid">{cards.map(([label, value, note]) => <article className="metric-card" key={label}><span>{label}</span><strong>{value}</strong><small>{note}</small></article>)}</div><div className="panel"><div className="panel-title"><span>Findings by severity</span><span className="muted">Reported by the API</span></div>{summary ? Object.entries(summary.finding_count_by_severity).map(([severity, count]) => <div className="availability-row" key={severity}><span>{severity}</span><strong>{count}</strong></div>) : <EmptyState title="Severity data pending" description="Completed analyzer output will populate this breakdown." compact />}</div><div className="panel"><div className="panel-title"><span>Analyzer outcomes</span><span className="muted">Worker evidence</span></div>{summary?.analyzer_outcomes?.length ? summary.analyzer_outcomes.map((item) => <div className="availability-row" key={item.analyzer}><span>{item.analyzer}</span><span className={`availability-${item.status}`}>{item.status}</span><small>{item.tool}</small></div>) : <EmptyState title="Analyzer evidence pending" description="Completed analyzer output will populate this list." compact />}</div><div className="panel"><div className="panel-title"><span>Optional AI explanation</span><span className="muted">Always grounded in stored evidence</span></div><button className="secondary-button" disabled={!summary || enrichmentBusy} onClick={() => void explain()} type="button">{enrichmentBusy ? 'Generating...' : 'Explain deterministic summary'}</button>{enrichmentError && <p className="error-copy" role="alert">{enrichmentError}</p>}{enrichment && <div className="ai-result"><strong>{enrichment.ai_generated ? 'AI-generated explanation' : 'AI enrichment disabled'}</strong>{enrichment.text && <p>{enrichment.text}</p>}{enrichment.citations.length > 0 && <small>Citations: {enrichment.citations.join(', ')}</small>}</div>}</div></section>
}

function HistoryView({ analysisId, status }: { analysisId: string | null; status: AnalysisStatus | null }) {
  return <section className="page-grid"><div className="panel table-panel"><div className="panel-title"><span>Analysis history</span><span className="muted">Latest first</span></div>{analysisId ? <div className="history-row"><code>{analysisId}</code><span className={`status-badge status-${status}`}>{status}</span><button type="button" onClick={() => { window.location.hash = 'overview' }}>Open overview</button></div> : <EmptyState title="No analyses" description="Submit a repository to create your first analysis run." compact />}</div></section>
}

function HotspotsView({ hotspots, status, error, repositoryUrl, analysisId, onSelectPath }: { hotspots: FileInsight[]; status: AnalysisStatus | null; error: string | null; repositoryUrl: string | null; analysisId: string | null; onSelectPath: (path: string) => void }) {
  const [sort, setSort] = useState<HotspotSort>({ column: 'hotspot_score', direction: 'desc' })
  const [filters, setFilters] = useState<HotspotFilters>({ risks: [] })
  const [exportBusy, setExportBusy] = useState(false)
  const filteredHotspots = useMemo(() => filterHotspots(hotspots, filters), [filters, hotspots])
  const orderedHotspots = useMemo(() => sortHotspots(filteredHotspots, sort), [filteredHotspots, sort])
  const toggleRisk = (risk: (typeof HOTSPOT_RISKS)[number]) => {
    setFilters((current) => ({
      risks: current.risks.includes(risk) ? current.risks.filter((item) => item !== risk) : [...current.risks, risk],
    }))
  }
  const clearFilters = () => setFilters({ risks: [] })
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
      const file = createHotspotsMarkdownExport({ repositoryUrl, analysisId, hotspots: exportRows, totalHotspotsLoaded: hotspots.length, filters, sort, details: Object.fromEntries(detailEntries), exportedAt: new Date() })
      downloadMarkdownFile(file)
    } finally {
      setExportBusy(false)
    }
  }
  if (status !== 'completed') return <EmptyState title="Hotspots pending" description="Hotspots appear after deterministic analysis completes." />
  if (error && hotspots.length === 0) return <EmptyState title="Hotspots unavailable" description={error} />
  if (hotspots.length === 0) return <EmptyState title="No hotspots" description="No file reached the configured hotspot threshold." />
  const sortLabel = HOTSPOT_COLUMNS.find(({ key }) => key === sort.column)?.label ?? sort.column
  return <section className="page-grid"><div className="panel table-panel"><div className="panel-title"><span>Hotspots ({filteredHotspots.length === hotspots.length ? hotspots.length : `${filteredHotspots.length} of ${hotspots.length}`})</span><div className="table-actions"><fieldset className="finding-filter-group"><legend>Risk</legend>{HOTSPOT_RISKS.map((risk) => <label key={risk}><input checked={filters.risks.includes(risk)} onChange={() => toggleRisk(risk)} type="checkbox" />{risk.charAt(0).toUpperCase() + risk.slice(1)}</label>)}</fieldset>{filters.risks.length > 0 && <button className="secondary-button" onClick={clearFilters} type="button">Clear filters</button>}<button className="secondary-button" disabled={orderedHotspots.length === 0 || exportBusy} onClick={() => void exportHotspots()} type="button">{exportBusy ? 'Exporting...' : 'Export hotspots (.md)'}</button></div></div>{filteredHotspots.length === 0 ? <EmptyState title="No hotspots match the selected filters." description="Clear the risk filter to show hotspots again." compact /> : <div className="findings-table-wrap"><table className="findings-table"><caption className="sr-only">Hotspots sorted by {sortLabel}</caption><thead><tr>{HOTSPOT_COLUMNS.map(({ key, label }) => <th aria-sort={sort.column === key ? (sort.direction === 'asc' ? 'ascending' : 'descending') : 'none'} key={key} scope="col"><button className="table-sort-button" onClick={() => setSort((current) => toggleHotspotSort(current, key as HotspotColumnKey))} type="button">{label}{sort.column === key && <span aria-hidden="true" className="sort-indicator">{sort.direction === 'asc' ? '↑' : '↓'}</span>}</button></th>)}</tr></thead><tbody>{orderedHotspots.map((hotspot) => <tr key={hotspot.path}><td><button className="path-link" onClick={() => onSelectPath(hotspot.path)} type="button"><code>{hotspot.path}</code></button></td><td>{hotspot.hotspot_score.toFixed(2)}</td><td>{hotspot.risk ? `${hotspot.risk.score.toFixed(2)} (${hotspotRisk(hotspot)})` : 'Unavailable'}</td><td>{formatHotspotComponents(hotspot)}</td></tr>)}</tbody></table></div>}</div></section>
}

function FileDetailView({ detail, path, files, status, busy, error, catalogError, onSelectPath }: { detail: FileDetail | null; path: string | null; files: FileInsight[]; status: AnalysisStatus | null; busy: boolean; error: string | null; catalogError: string | null; onSelectPath: (path: string) => void }) {
  if (status !== 'completed') return <EmptyState title="File detail pending" description="File-level evidence appears after deterministic analysis completes." />
  if (catalogError && files.length === 0 && !path) return <EmptyState title="File catalog unavailable" description={catalogError} />
  if (!path && files.length === 0) return <EmptyState title="No file evidence" description="The completed analysis did not include file-level evidence." />
  if (busy) return <EmptyState title="Loading file detail" description={`Loading evidence for ${path}.`} />
  if (error || !detail) return <EmptyState title="File detail unavailable" description={error || 'No stored evidence exists for this file.'} />
  return <section className="page-grid"><div className="panel file-picker"><label htmlFor="file-select">File</label><select id="file-select" value={path || ''} onChange={(event) => onSelectPath(event.target.value)}>{files.map((file) => <option key={file.path} value={file.path}>{file.path}</option>)}</select></div><div className="section-heading"><div><p className="kicker">File evidence</p><h2><code>{detail.path}</code></h2></div><span className="status-badge status-completed">completed</span></div><div className="metric-grid"><article className="metric-card"><span>Hotspot score</span><strong>{detail.hotspot_score.toFixed(2)}</strong><small>History and finding evidence</small></article><article className="metric-card"><span>Risk</span><strong>{detail.risk ? detail.risk.score.toFixed(2) : '—'}</strong><small>{detail.risk ? `${detail.risk.category} · v${detail.risk.version}` : 'Unavailable'}</small></article><article className="metric-card"><span>Findings</span><strong>{detail.findings.length}</strong><small>Stored analyzer evidence</small></article></div><div className="panel"><div className="panel-title"><span>Risk components</span><span className="muted">Normalized values</span></div>{Object.entries(detail.risk?.components ?? {}).map(([name, value]) => <div className="availability-row" key={name}><span>{name}</span><strong>{value.toFixed(2)}</strong></div>)}</div><div className="panel"><div className="panel-title"><span>Findings in file</span></div>{detail.findings.length ? detail.findings.map((finding) => <div className="availability-row" key={`${finding.rule_id}-${finding.start_line}`}><span>{finding.message}</span><span className={`severity-badge severity-${finding.severity}`}>{finding.severity}</span></div>) : <EmptyState title="No findings" description="No finding is attached to this file." compact />}</div></section>
}

function QualityGateView({ summary }: { summary: AnalysisSummaryResponse['summary'] }) {
  if (!summary?.quality_gate) return <section className="page-grid"><div className="panel"><div className="panel-title"><span>Quality gate</span><span className="muted">Evidence only</span></div><EmptyState title="Quality-gate data unavailable" description="The completed analysis did not include a quality-gate evaluation." compact /></div></section>
  const gate = summary.quality_gate
  const observed = gate.observed
  return <section className="page-grid"><div className="panel"><div className="panel-title"><span>Quality gate</span><span className={`status-badge status-${gate.status === 'failed' ? 'failed' : 'completed'}`}>{gate.status === 'not_configured' ? 'not configured' : gate.passed ? 'passed' : 'failed'}</span></div><div className="metric-grid"><article className="metric-card"><span>Risk score</span><strong>{observed.risk_score === null ? '—' : observed.risk_score.toFixed(2)}</strong><small>Observed in this analysis</small></article><article className="metric-card"><span>New critical findings</span><strong>{observed.new_critical_findings}</strong><small>Compared with baseline</small></article><article className="metric-card"><span>New hotspots</span><strong>{observed.new_hotspots}</strong><small>Compared with baseline</small></article></div>{gate.status === 'not_configured' && <EmptyState title="Quality gate not configured" description="Configure at least one quality-gate threshold to evaluate this analysis." compact />}{gate.failures.length ? gate.failures.map((failure) => <div className="availability-row" key={failure.code}><strong>{failure.code}</strong><span>{failure.detail}</span></div>) : gate.status !== 'not_configured' && <EmptyState title="All configured rules passed" description="No quality-gate failure was reported." compact />}</div></section>
}

function EmptyState({ title, description, compact = false }: { title: string; description: string; compact?: boolean }) {
  return <div className={`empty-state ${compact ? 'is-compact' : ''}`}><span className="empty-mark">[ ]</span><div><strong>{title}</strong><p>{description}</p></div></div>
}

export default App
