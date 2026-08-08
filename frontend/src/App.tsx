import { useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import {
  apiDocsUrl,
  createAnalysis,
  getAnalysisStatus,
  getAnalysisSummary,
  getAnalysisFindings,
  requestEnrichment,
  type AnalysisStatus,
  type AnalysisSummaryResponse,
  type AnalysisFinding,
  type EnrichmentResponse,
} from './api'
import { createFindingsMarkdownExport, downloadMarkdownFile } from './findingsExport'
import {
  FINDING_COLUMNS,
  FINDING_SEVERITIES,
  categoryLabel,
  displaySeverity,
  reconcileFindingSort,
  severityCounts,
  sortFindings,
  toggleFindingSort,
  type FindingColumnKey,
  type FindingSort,
} from './findingsPresentation'

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
          if (nextStatus.status === 'completed') getAnalysisFindings(analysisId).then(setFindings).catch(() => setFindings([]))
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
        {activeView === 'findings' && <FindingsView findings={findings} status={status} summary={summary} error={error} repositoryUrl={analyzedRepositoryUrl} analysisId={analysisId} />}
        {activeView === 'hotspots' && <GraphView />}
        {activeView === 'files' && <EmptyState title="Select a file from findings" description="File-level score breakdowns will appear when finding data is available." />}
        {activeView === 'quality' && <QualityGateView />}
      </main>
    </div>
  )
}

function FindingsView({ findings, status, summary, error, repositoryUrl, analysisId }: { findings: AnalysisFinding[]; status: AnalysisStatus | null; summary: AnalysisSummaryResponse['summary']; error: string | null; repositoryUrl: string | null; analysisId: string | null }) {
  const [sort, setSort] = useState<FindingSort>({ column: 'severity', direction: 'desc' })
  const [visibleColumns, setVisibleColumns] = useState<FindingColumnKey[]>(() => FINDING_COLUMNS.map(({ key }) => key))

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
      findings,
      exportedAt: new Date(),
    })
    downloadMarkdownFile(file)
  }
  const counts = severityCounts(findings)
  const orderedFindings = sortFindings(findings, sort)
  const toggleSort = (column: FindingColumnKey) => setSort((current) => toggleFindingSort(current, column))
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
            <button className="secondary-button" onClick={exportFindings} type="button">Export findings (.md)</button>
          </div>
        </div>
        {visibleColumns.length === 0 ? (
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
                          <code>{finding.path}:{finding.start_line}{finding.end_line !== finding.start_line ? `-${finding.end_line}` : ''}</code>
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
  const cards = [
    ['Risk score', '-', 'Risk model data pending'],
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

function GraphView() {
  return <section className="page-grid"><div className="panel graph-placeholder"><div className="panel-title"><span>Dependency graph</span><span className="muted">Bounded view</span></div><div className="graph-lines"><span /><span /><span /><span /></div><EmptyState title="Graph data pending" description="The graph view will render bounded structural evidence when the analysis API returns dependency edges." compact /></div><div className="metric-grid"><article className="metric-card"><span>Cycles</span><strong>-</strong><small>Structural evidence only</small></article><article className="metric-card"><span>Top hotspot</span><strong>-</strong><small>No fabricated metrics</small></article></div></section>
}

function QualityGateView() {
  return <section className="page-grid"><div className="panel"><div className="panel-title"><span>Quality gate</span><span className="muted">Evidence only</span></div><EmptyState title="Quality-gate result pending" description="The API will report pass or fail criteria after quality-gate evaluation is connected to an analysis run." compact /></div></section>
}

function EmptyState({ title, description, compact = false }: { title: string; description: string; compact?: boolean }) {
  return <div className={`empty-state ${compact ? 'is-compact' : ''}`}><span className="empty-mark">[ ]</span><div><strong>{title}</strong><p>{description}</p></div></div>
}

export default App
