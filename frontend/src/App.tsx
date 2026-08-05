import { useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import {
  apiDocsUrl,
  createAnalysis,
  getAnalysisStatus,
  getAnalysisSummary,
  getAnalyzerAvailability,
  type AnalysisStatus,
  type AnalysisSummaryResponse,
  type AnalyzerAvailability,
} from './api'

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
  const [analysisId, setAnalysisId] = useState<string | null>(null)
  const [status, setStatus] = useState<AnalysisStatus | null>(null)
  const [summary, setSummary] = useState<AnalysisSummaryResponse['summary']>(null)
  const [availability, setAvailability] = useState<AnalyzerAvailability[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const onHashChange = () => setView(viewFromHash())
    window.addEventListener('hashchange', onHashChange)
    getAnalyzerAvailability().then(setAvailability).catch(() => setAvailability([]))
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

  const navigate = (next: View) => {
    window.location.hash = next
    setView(next)
  }

  const submitRepository = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const accepted = await createAnalysis(repositoryUrl.trim())
      setAnalysisId(accepted.analysis_id)
      setStatus(accepted.status)
      setSummary(null)
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
        {activeView === 'overview' && <OverviewView analysisId={analysisId} status={status} summary={summary} availability={availability} />}
        {activeView === 'findings' && <EmptyState title="Findings arrive with the completed analysis" description="The current API has not returned findings for this analysis yet." />}
        {activeView === 'hotspots' && <GraphView />}
        {activeView === 'files' && <EmptyState title="Select a file from findings" description="File-level score breakdowns will appear when finding data is available." />}
        {activeView === 'quality' && <QualityGateView />}
      </main>
    </div>
  )
}

function OverviewView({ analysisId, status, summary, availability }: { analysisId: string | null; status: AnalysisStatus | null; summary: AnalysisSummaryResponse['summary']; availability: AnalyzerAvailability[] }) {
  const severityTotal = summary ? Object.values(summary.finding_count_by_severity).reduce((total, value) => total + value, 0) : null
  const cards = [
    ['Risk score', '-', 'Risk model data pending'],
    ['Findings', severityTotal === null ? 'â€”' : String(severityTotal), 'From completed analyzer output'],
    ['Files analyzed', summary ? String(summary.analyzed_file_count) : 'â€”', 'Repository evidence'],
    ['Duration', summary ? `${summary.duration_seconds.toFixed(1)}s` : 'â€”', 'Worker execution time'],
  ]
  return <section className="page-grid"><div className="section-heading"><div><p className="kicker">Analysis overview</p><h2>{analysisId ? `Run ${analysisId.slice(0, 8)}` : 'No active analysis'}</h2></div><span className={`status-badge status-${status}`}>{status || 'idle'}</span></div><div className="metric-grid">{cards.map(([label, value, note]) => <article className="metric-card" key={label}><span>{label}</span><strong>{value}</strong><small>{note}</small></article>)}</div><div className="panel"><div className="panel-title"><span>Findings by severity</span><span className="muted">Reported by the API</span></div>{summary ? Object.entries(summary.finding_count_by_severity).map(([severity, count]) => <div className="availability-row" key={severity}><span>{severity}</span><strong>{count}</strong></div>) : <EmptyState title="Severity data pending" description="Completed analyzer output will populate this breakdown." compact />}</div><div className="panel"><div className="panel-title"><span>Analyzer availability</span><span className="muted">No secrets / no arbitrary execution</span></div>{availability.length ? availability.map((item) => <div className="availability-row" key={item.analyzer}><span>{item.analyzer}</span><span className={`availability-${item.status}`}>{item.status}</span><small>{item.tool}</small></div>) : <EmptyState title="Availability unavailable" description="Analyzer availability will be reported when the API is reachable." compact />}</div></section>
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
