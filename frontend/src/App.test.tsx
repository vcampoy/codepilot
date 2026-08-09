import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

type Deferred<T> = {
  promise: Promise<T>
  resolve: (value: T) => void
  reject: (reason?: unknown) => void
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((nextResolve, nextReject) => {
    resolve = nextResolve
    reject = nextReject
  })
  return { promise, resolve, reject }
}

const fixtures = vi.hoisted(() => ({
  createAnalysis: vi.fn(),
  getAnalysisStatus: vi.fn(),
  getAnalysisSummary: vi.fn(),
  getAnalysisFindings: vi.fn(),
  getAnalysisHotspots: vi.fn(),
  getAnalysisFiles: vi.fn(),
  getAnalysisFileDetail: vi.fn(),
  requestEnrichment: vi.fn(),
  downloadMarkdownFile: vi.fn(),
}))

vi.mock('./api', () => ({
  ...fixtures,
  apiDocsUrl: 'http://localhost:8000/docs',
}))

vi.mock('./findingsExport', async () => ({
  ...(await vi.importActual<typeof import('./findingsExport')>('./findingsExport')),
  downloadMarkdownFile: fixtures.downloadMarkdownFile,
}))

import App from './App'

const completedStatus = {
  analysis_id: 'analysis-1',
  status: 'completed',
  commit_sha: 'a'.repeat(40),
  failure_message: null,
  retryable: false,
} as const

const summary = {
  analysis_id: 'analysis-1',
  status: 'completed',
  summary: {
    analyzed_file_count: 2,
    source_lines: 20,
    finding_count_by_severity: { warning: 1 },
    duration_seconds: 1.2,
    analyzer_outcomes: [],
    risk_assessment: {
      score: 0.8,
      category: 'high',
      version: '1.0',
      components: { finding_severity: 1 },
      weights: { finding_severity: 0.3 },
    },
    quality_gate: {
      passed: true,
      configured: false,
      status: 'not_configured',
      failures: [],
      thresholds: { max_new_critical_findings: null, max_risk_score: null, max_new_hotspots: null },
      observed: { new_critical_findings: 0, risk_score: 0.8, new_hotspots: 1 },
    },
  },
} as const

const finding = {
  path: 'src/main.py',
  rule_id: 'PY001',
  analyzer: 'python.ruff',
  severity: 'warning',
  message: 'Avoid this pattern.',
  start_line: 4,
  end_line: 4,
  category: 'quality',
} as const

const insight = {
  path: 'src/main.py',
  hotspot_score: 0.8,
  risk: summary.summary.risk_assessment,
  metrics: { finding_severity: 1 },
} as const

function configureCompletedRun() {
  fixtures.createAnalysis.mockResolvedValue({ analysis_id: 'analysis-1', status: 'queued' })
  fixtures.getAnalysisStatus.mockResolvedValue(completedStatus)
  fixtures.getAnalysisSummary.mockResolvedValue(summary)
  fixtures.getAnalysisFileDetail.mockResolvedValue({ ...insight, findings: [] })
}

beforeEach(() => {
  window.location.hash = ''
  Object.values(fixtures).forEach((mock) => mock.mockReset())
})

afterEach(() => cleanup())

describe('completed analysis result loading', () => {
  it('filters findings by severity and type', async () => {
    const findings = [
      finding,
      { ...finding, rule_id: 'PY002', severity: 'critical', message: 'Critical security issue.', category: 'security' },
      { ...finding, rule_id: 'PY003', severity: 'info', message: 'Informational quality issue.', category: 'quality' },
    ] as const
    configureCompletedRun()
    fixtures.getAnalysisFindings.mockResolvedValue(findings)
    fixtures.getAnalysisHotspots.mockResolvedValue([insight])
    fixtures.getAnalysisFiles.mockResolvedValue({ items: [insight], total: 1, limit: 100, offset: 0 })

    render(<App />)
    fireEvent.submit(screen.getByRole('button', { name: 'Analyze repository' }).closest('form')!, {
      preventDefault: () => undefined,
    })
    fireEvent.click(await screen.findByRole('button', { name: 'Findings' }))
    await waitFor(() => expect(screen.getByText('Findings (3)')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('checkbox', { name: 'Critical' }))
    expect(screen.getByText('Critical security issue.')).toBeInTheDocument()
    expect(screen.queryByText('Avoid this pattern.')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('checkbox', { name: 'Security' }))
    expect(screen.getByText('Critical security issue.')).toBeInTheDocument()
    expect(screen.queryByText('Informational quality issue.')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('checkbox', { name: 'Security' }))
    fireEvent.click(screen.getByRole('checkbox', { name: 'Quality' }))
    expect(screen.queryByText('Critical security issue.')).not.toBeInTheDocument()
    expect(screen.getByText('No findings match the selected filters.')).toBeInTheDocument()
  })

  it('disables findings export when filters hide every finding', async () => {
    configureCompletedRun()
    fixtures.getAnalysisFindings.mockResolvedValue([finding])
    fixtures.getAnalysisHotspots.mockResolvedValue([insight])
    fixtures.getAnalysisFiles.mockResolvedValue({ items: [insight], total: 1, limit: 100, offset: 0 })

    render(<App />)
    fireEvent.submit(screen.getByRole('button', { name: 'Analyze repository' }).closest('form')!, {
      preventDefault: () => undefined,
    })
    fireEvent.click(await screen.findByRole('button', { name: 'Findings' }))
    await waitFor(() => expect(screen.getByText('Findings (1)')).toBeInTheDocument())

    const exportButton = screen.getByRole('button', { name: 'Export findings (.md)' })
    expect(exportButton).toBeEnabled()
    fireEvent.click(screen.getByRole('checkbox', { name: 'Critical' }))
    expect(screen.getByText('No findings match the selected filters.')).toBeInTheDocument()
    expect(exportButton).toBeDisabled()
  })

  it('keeps findings and hotspots after the polling status changes to completed', async () => {
    const findings = deferred<typeof finding[]>()
    const hotspots = deferred<typeof insight[]>()
    configureCompletedRun()
    fixtures.getAnalysisFindings.mockReturnValue(findings.promise)
    fixtures.getAnalysisHotspots.mockReturnValue(hotspots.promise)
    fixtures.getAnalysisFiles.mockResolvedValue({ items: [insight], total: 1, limit: 100, offset: 0 })

    render(<App />)
    fireEvent.submit(screen.getByRole('button', { name: 'Analyze repository' }).closest('form')!, {
      preventDefault: () => undefined,
    })
    await waitFor(() => expect(fixtures.getAnalysisFindings).toHaveBeenCalled())

    findings.resolve([finding])
    hotspots.resolve([insight])
    fireEvent.click(screen.getByRole('button', { name: 'Findings' }))
    await waitFor(() => expect(screen.getByText('Findings (1)')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Hotspots' }))
    await waitFor(() => expect(screen.getByText('Hotspots (1)')).toBeInTheDocument())
  })

  it('keeps successful findings visible when hotspots fail', async () => {
    configureCompletedRun()
    fixtures.getAnalysisFindings.mockResolvedValue([finding])
    fixtures.getAnalysisHotspots.mockRejectedValue(new Error('Hotspots unavailable.'))
    fixtures.getAnalysisFiles.mockResolvedValue({ items: [insight], total: 1, limit: 100, offset: 0 })

    render(<App />)
    fireEvent.submit(screen.getByRole('button', { name: 'Analyze repository' }).closest('form')!, {
      preventDefault: () => undefined,
    })
    fireEvent.click(await screen.findByRole('button', { name: 'Findings' }))
    await waitFor(() => expect(screen.getByText('Findings (1)')).toBeInTheDocument())
  })

  it('filters, sorts, and exports hotspots using the visible rows', async () => {
    configureCompletedRun()
    const secondInsight = { ...insight, path: 'src/other.py', hotspot_score: 0.4, risk: { ...insight.risk!, score: 0.4, category: 'medium' }, metrics: { complexity: 0.4, coupling: 0.3 } }
    fixtures.getAnalysisFindings.mockResolvedValue([finding])
    fixtures.getAnalysisHotspots.mockResolvedValue([insight, secondInsight])
    fixtures.getAnalysisFiles.mockResolvedValue({ items: [insight, secondInsight], total: 2, limit: 100, offset: 0 })
    fixtures.getAnalysisFileDetail.mockImplementation(async (_id: string, path: string) => ({ ...(path === insight.path ? insight : secondInsight), findings: path === insight.path ? [finding] : [] }))

    render(<App />)
    fireEvent.submit(screen.getByRole('button', { name: 'Analyze repository' }).closest('form')!, { preventDefault: () => undefined })
    fireEvent.click(await screen.findByRole('button', { name: 'Hotspots' }))
    await waitFor(() => expect(screen.getByText('Hotspots (2)')).toBeInTheDocument())

    expect(screen.getByRole('button', { name: 'Export hotspots (.md)' })).toBeEnabled()
    fireEvent.click(screen.getByRole('checkbox', { name: 'High' }))
    expect(screen.getByText('Hotspots (1 of 2)')).toBeInTheDocument()
    expect(screen.queryByText('src/other.py')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Risk/ }))
    expect(screen.getByRole('columnheader', { name: /Risk/ })).toHaveAttribute('aria-sort', 'ascending')
  })

  it('exports visible hotspots, fetches related details, and tolerates one detail failure', async () => {
    configureCompletedRun()
    const secondInsight = { ...insight, path: 'src/other.py', hotspot_score: 0.4, risk: { ...insight.risk!, score: 0.4, category: 'medium' }, metrics: { complexity: 0.4 } }
    fixtures.getAnalysisFindings.mockResolvedValue([finding])
    fixtures.getAnalysisHotspots.mockResolvedValue([insight, secondInsight])
    fixtures.getAnalysisFiles.mockResolvedValue({ items: [insight, secondInsight], total: 2, limit: 100, offset: 0 })
    fixtures.getAnalysisFileDetail.mockImplementation(async (_id: string, path: string) => {
      if (path === secondInsight.path) throw new Error('partial detail failure')
      return { ...insight, findings: [finding] }
    })

    render(<App />)
    fireEvent.change(screen.getByLabelText('Repository URL'), { target: { value: 'https://github.com/acme/demo' } })
    fireEvent.submit(screen.getByRole('button', { name: 'Analyze repository' }).closest('form')!, { preventDefault: () => undefined })
    fireEvent.click(await screen.findByRole('button', { name: 'Hotspots' }))
    await waitFor(() => expect(screen.getByText('Hotspots (2)')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Export hotspots (.md)' }))
    await waitFor(() => expect(fixtures.downloadMarkdownFile).toHaveBeenCalledOnce())
    expect(fixtures.getAnalysisFileDetail).toHaveBeenCalledWith('analysis-1', 'src/main.py')
    expect(fixtures.getAnalysisFileDetail).toHaveBeenCalledWith('analysis-1', 'src/other.py')
    expect(fixtures.downloadMarkdownFile.mock.calls[0][0].content).toContain('Related findings: _Unavailable')
  })

  it('loads the first file in direct File detail view and shows quality evidence', async () => {
    configureCompletedRun()
    fixtures.getAnalysisFindings.mockResolvedValue([finding])
    fixtures.getAnalysisHotspots.mockResolvedValue([insight])
    fixtures.getAnalysisFiles.mockResolvedValue({ items: [insight], total: 1, limit: 100, offset: 0 })
    fixtures.getAnalysisFileDetail.mockResolvedValue({ ...insight, findings: [finding] })

    render(<App />)
    fireEvent.submit(screen.getByRole('button', { name: 'Analyze repository' }).closest('form')!, {
      preventDefault: () => undefined,
    })
    fireEvent.click(await screen.findByRole('button', { name: 'File detail' }))
    await waitFor(() => expect(screen.getByRole('heading', { name: 'src/main.py' })).toBeInTheDocument())
    expect(fixtures.getAnalysisFileDetail).toHaveBeenCalledWith('analysis-1', 'src/main.py', expect.objectContaining({ signal: expect.any(AbortSignal) }))

    fireEvent.click(screen.getByRole('button', { name: 'Quality gate' }))
    expect(screen.getByText('Risk score')).toBeInTheDocument()
    expect(screen.getByText('0.80')).toBeInTheDocument()
  })

  it('renders bounded source context, highlighted range, evidence, and remediation', async () => {
    configureCompletedRun()
    const contextualFinding = {
      ...finding,
      start_line: 3,
      end_line: 3,
      evidence: 'Unsafe call',
      remediation: 'Use a safe parser.',
      source_context: {
        start_line: 1,
        end_line: 5,
        lines: [
          { number: 1, text: 'one' },
          { number: 2, text: 'two' },
          { number: 3, text: 'eval(x)', highlighted: true },
          { number: 4, text: 'four' },
          { number: 5, text: 'five' },
        ],
      },
    }
    fixtures.getAnalysisFindings.mockResolvedValue([contextualFinding])
    fixtures.getAnalysisHotspots.mockResolvedValue([insight])
    fixtures.getAnalysisFiles.mockResolvedValue({ items: [insight], total: 1, limit: 100, offset: 0 })
    fixtures.getAnalysisFileDetail.mockResolvedValue({ ...insight, findings: [contextualFinding] })

    render(<App />)
    fireEvent.submit(screen.getByRole('button', { name: 'Analyze repository' }).closest('form')!, { preventDefault: () => undefined })
    fireEvent.click(await screen.findByRole('button', { name: 'File detail' }))
    await waitFor(() => expect(screen.getByText('eval(x)')).toBeInTheDocument())
    expect(screen.getByText('Unsafe call')).toBeInTheDocument()
    expect(screen.getByText('Use a safe parser.')).toBeInTheDocument()
    expect(screen.getByText('eval(x)').closest('.source-line')).toHaveClass('source-line-highlight')
  })

  it('renders configured quality-gate pass and failure states', async () => {
    configureCompletedRun()
    fixtures.getAnalysisFindings.mockResolvedValue([finding])
    fixtures.getAnalysisHotspots.mockResolvedValue([insight])
    fixtures.getAnalysisFiles.mockResolvedValue({ items: [insight], total: 1, limit: 100, offset: 0 })

    fixtures.getAnalysisSummary.mockResolvedValueOnce({
      ...summary,
      summary: {
        ...summary.summary,
        quality_gate: {
          ...summary.summary.quality_gate,
          configured: true,
          status: 'failed',
          passed: false,
          failures: [{ code: 'risk-score', detail: 'Risk score exceeds limit.' }],
          thresholds: { max_new_critical_findings: 0, max_risk_score: 0.7, max_new_hotspots: 2 },
        },
      },
    })

    render(<App />)
    fireEvent.submit(screen.getByRole('button', { name: 'Analyze repository' }).closest('form')!, {
      preventDefault: () => undefined,
    })
    fireEvent.click(await screen.findByRole('button', { name: 'Quality gate' }))
    await waitFor(() => expect(screen.getByText('failed')).toBeInTheDocument())
    expect(screen.getByText('risk-score')).toBeInTheDocument()

    cleanup()
    fixtures.getAnalysisSummary.mockResolvedValueOnce({
      ...summary,
      summary: {
        ...summary.summary,
        quality_gate: {
          ...summary.summary.quality_gate,
          configured: true,
          status: 'passed',
          passed: true,
          failures: [],
          thresholds: { max_new_critical_findings: 1, max_risk_score: 0.9, max_new_hotspots: 2 },
        },
      },
    })
    render(<App />)
    fireEvent.submit(screen.getByRole('button', { name: 'Analyze repository' }).closest('form')!, {
      preventDefault: () => undefined,
    })
    fireEvent.click(await screen.findByRole('button', { name: 'Quality gate' }))
    await waitFor(() => expect(screen.getByText('All configured rules passed')).toBeInTheDocument())
  })
})
