import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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

const LLM_PROVIDERS = vi.hoisted(() => [
  { id: 'openai', label: 'OpenAI' }, { id: 'anthropic', label: 'Anthropic' },
  { id: 'openrouter', label: 'OpenRouter' }, { id: 'google', label: 'Google' },
  { id: 'kimi', label: 'Kimi' }, { id: 'grok', label: 'Grok' },
  { id: 'minimax', label: 'MiniMax' }, { id: 'nvidia', label: 'NVIDIA' },
  { id: 'deepseek', label: 'DeepSeek' },
] as const)

const fixtures = vi.hoisted(() => ({
  createAnalysis: vi.fn(),
  getRepositoryBranches: vi.fn(),
  getAnalysisStatus: vi.fn(),
  getAnalysisSummary: vi.fn(),
  getAnalysisFindings: vi.fn(),
  getAnalysisHotspots: vi.fn(),
  getAnalysisFiles: vi.fn(),
  getAnalysisFileDetail: vi.fn(),
  getProjects: vi.fn().mockResolvedValue({ items: [] }),
  getProjectAnalyses: vi.fn(),
  getAnalysisHistory: vi.fn().mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 }),
  deleteAnalysis: vi.fn(),
  getQualityPolicy: vi.fn(),
  saveQualityPolicy: vi.fn(),
  importQualityProfile: vi.fn(),
  getLlmConfiguration: vi.fn(),
  getLlmProviders: vi.fn(),
  saveLlmConfiguration: vi.fn(),
  requestEnrichment: vi.fn(),
  getFixConfiguration: vi.fn(),
  saveFixConfiguration: vi.fn(),
  createFixJob: vi.fn(),
  getFixJob: vi.fn(),
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

const alternateInsight = { ...insight, path: 'src/other.py' } as const

const historyItem = {
  analysis_id: 'analysis-1',
  project_id: 'project-1',
  repository_name: 'demo',
  repository_url: 'https://github.com/acme/demo',
  created_at: '2026-08-09T12:00:00Z',
  risk_score: 0.8,
  risk_category: 'high',
  finding_count: 1,
  analyzed_file_count: 2,
  duration_seconds: 1.2,
} as const

const projectItem = {
  project_id: 'project-1',
  name: 'demo',
  repository_url: 'https://github.com/acme/demo',
  created_at: '2026-08-08T12:00:00Z',
  updated_at: '2026-08-09T12:00:00Z',
} as const

const emptyProjectCatalog = { items: [], total: 0, limit: 20, offset: 0 } as const
const persistedProjectCatalog = { items: [projectItem], total: 1, limit: 20, offset: 0 } as const

const filterFindings = [
  finding,
  { ...finding, rule_id: 'PY002', severity: 'critical', message: 'Critical security issue.', category: 'security' },
  { ...finding, rule_id: 'PY003', severity: 'info', message: 'Informational quality issue.', category: 'quality' },
] as const

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
} as const

const contextualFindings = [contextualFinding] as const

const secondContextualFinding = {
  ...contextualFinding,
  rule_id: 'PY002',
  message: 'Another unsafe pattern.',
  start_line: 8,
  end_line: 8,
  source_context: {
    start_line: 7,
    end_line: 9,
    lines: [
      { number: 7, text: 'before()' },
      { number: 8, text: 'danger()', highlighted: true },
      { number: 9, text: 'after()' },
    ],
  },
} as const

const multipleContextualFindings = [contextualFinding, secondContextualFinding] as const
const DEFAULT_LLM_CONFIGURATION = {
  enabled: false,
  provider: 'openai',
  model: 'gpt-4o-mini',
  api_key_configured: false,
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
  fixtures.getProjects.mockResolvedValue(emptyProjectCatalog)
  fixtures.getRepositoryBranches.mockResolvedValue({ branches: ['main', 'release'], default_branch: 'main' })
  fixtures.getAnalysisHistory.mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 })
  fixtures.getLlmConfiguration.mockResolvedValue(DEFAULT_LLM_CONFIGURATION)
  fixtures.getLlmProviders.mockResolvedValue({ providers: LLM_PROVIDERS })
  fixtures.getFixConfiguration.mockResolvedValue({ rules: '' })
})

afterEach(() => cleanup())

it('loads branches on repository blur and submits the selected branch', async () => {
  fixtures.createAnalysis.mockResolvedValue({ analysis_id: 'analysis-1', status: 'queued' })

  render(<App />)

  const repositoryInput = screen.getByLabelText('Repository URL')
  fireEvent.change(repositoryInput, { target: { value: 'https://github.com/acme/demo' } })
  fireEvent.blur(repositoryInput)

  const branchSelect = await screen.findByRole('combobox', { name: 'Branch' })
  expect(branchSelect).toHaveValue('main')
  fireEvent.change(branchSelect, { target: { value: 'release' } })
  fireEvent.submit(repositoryInput.closest('form')!, { preventDefault: () => undefined })

  await waitFor(() => expect(fixtures.createAnalysis).toHaveBeenCalledWith(
    'https://github.com/acme/demo',
    'release',
  ))
  expect(fixtures.getRepositoryBranches).toHaveBeenCalledWith('https://github.com/acme/demo')
})

it('uses the remote default branch when submitting before branch discovery finishes', async () => {
  fixtures.createAnalysis.mockResolvedValue({ analysis_id: 'analysis-1', status: 'queued' })
  fixtures.getRepositoryBranches.mockResolvedValue({ branches: ['main', 'release'], default_branch: 'release' })

  render(<App />)
  const repositoryInput = screen.getByLabelText('Repository URL')
  fireEvent.change(repositoryInput, { target: { value: ' https://github.com/acme/demo ' } })
  fireEvent.submit(repositoryInput.closest('form')!, { preventDefault: () => undefined })

  await waitFor(() => expect(fixtures.createAnalysis).toHaveBeenCalledWith(
    'https://github.com/acme/demo',
    'release',
  ))
})

it('shows branch discovery loading and error states and clears stale options', async () => {
  const pending = deferred<{ branches: string[]; default_branch: string }>()
  fixtures.getRepositoryBranches
    .mockReturnValueOnce(pending.promise)
    .mockRejectedValueOnce('Branch lookup failed.')
    .mockRejectedValueOnce(new Error('Branch lookup failed.'))

  render(<App />)
  const repositoryInput = screen.getByLabelText('Repository URL')
  expect(screen.queryByRole('combobox', { name: 'Branch' })).not.toBeInTheDocument()
  fireEvent.change(repositoryInput, { target: { value: 'https://github.com/acme/demo' } })
  fireEvent.blur(repositoryInput)

  const loadingSelect = await screen.findByRole('combobox', { name: 'Branch' })
  expect(loadingSelect).toBeDisabled()
  pending.resolve({ branches: ['main', 'release'], default_branch: 'main' })
  expect(await screen.findByRole('option', { name: 'release' })).toBeInTheDocument()
  expect(loadingSelect).not.toBeDisabled()

  fireEvent.blur(repositoryInput)
  await waitFor(() => expect(screen.queryByRole('combobox', { name: 'Branch' })).not.toBeInTheDocument())

  fireEvent.change(repositoryInput, { target: { value: 'https://github.com/acme/other' } })
  expect(screen.queryByRole('combobox', { name: 'Branch' })).not.toBeInTheDocument()
  fireEvent.blur(repositoryInput)
  expect(await screen.findByText('Branch lookup failed.')).toBeInTheDocument()
})

it('ignores a stale branch response after the repository URL changes', async () => {
  const firstLookup = deferred<{ branches: string[]; default_branch: string }>()
  fixtures.getRepositoryBranches
    .mockReturnValueOnce(firstLookup.promise)
    .mockResolvedValueOnce({ branches: ['develop'], default_branch: 'develop' })

  render(<App />)
  const repositoryInput = screen.getByLabelText('Repository URL')
  fireEvent.change(repositoryInput, { target: { value: 'https://github.com/acme/first' } })
  fireEvent.blur(repositoryInput)
  fireEvent.change(repositoryInput, { target: { value: 'https://github.com/acme/second' } })
  fireEvent.blur(repositoryInput)

  const branchSelect = await screen.findByRole('combobox', { name: 'Branch' })
  expect(branchSelect).toHaveValue('develop')
  firstLookup.resolve({ branches: ['stale'], default_branch: 'stale' })
  await waitFor(() => expect(screen.queryByRole('option', { name: 'stale' })).not.toBeInTheDocument())
  expect(branchSelect).toHaveValue('develop')
})

describe('analysis history and quality KPI', () => {
  it('renders persisted repositories immediately on page load', async () => {
    fixtures.getProjects.mockResolvedValue(persistedProjectCatalog)

    render(<App />)

    expect(await screen.findByRole('table', { name: 'Persisted repositories' })).toBeInTheDocument()
    expect(screen.getByRole('rowheader', { name: 'demo' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'https://github.com/acme/demo' })).toBeInTheDocument()
    expect(screen.getByText(/Aug 9, 2026/)).toBeInTheDocument()
    expect(screen.queryByText('No repositories yet')).not.toBeInTheDocument()
  })

  it('shows repository loading state while the catalog request is pending', async () => {
    const pending = deferred<typeof persistedProjectCatalog>()
    fixtures.getProjects.mockReturnValue(pending.promise)

    render(<App />)

    expect(screen.getByText('Loading repositories')).toBeInTheDocument()
    pending.resolve(persistedProjectCatalog)
    expect(await screen.findByRole('table', { name: 'Persisted repositories' })).toBeInTheDocument()
  })

  it('disables repository submission while queueing and restores it after resolution', async () => {
    const pending = deferred<{ analysis_id: string; status: 'queued' }>()
    fixtures.createAnalysis.mockReturnValue(pending.promise)

    render(<App />)

    fireEvent.submit(screen.getByRole('button', { name: 'Analyze repository' }).closest('form')!, {
      preventDefault: () => undefined,
    })

    const queueButton = await screen.findByRole('button', { name: 'Queueing...' })
    expect(queueButton).toBeDisabled()

    pending.resolve({ analysis_id: 'analysis-1', status: 'queued' })
    await waitFor(() => expect(screen.getByRole('button', { name: 'Repositories' })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Repositories' }))

    expect(await screen.findByRole('button', { name: 'Analyze repository' })).not.toBeDisabled()
  })

  it('renders the empty repository state when the catalog is empty', async () => {
    fixtures.getProjects.mockResolvedValue(emptyProjectCatalog)

    render(<App />)

    expect(await screen.findByText('No repositories yet')).toBeInTheDocument()
  })

  it('keeps analysis history available when the project catalog fails', async () => {
    fixtures.getProjects.mockRejectedValue('projects failure')
    fixtures.getAnalysisHistory.mockResolvedValue({
      items: [historyItem],
      total: 1,
      limit: 20,
      offset: 0,
    })

    render(<App />)

    fireEvent.click(await screen.findByRole('button', { name: 'Analysis history' }))

    expect(await screen.findByRole('rowheader', { name: /demo/ })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Repositories' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Repositories unavailable.')
  })

  it('shows the history fallback when the history request fails with a non-error value', async () => {
    fixtures.getAnalysisHistory.mockRejectedValue('history failure')

    render(<App />)

    fireEvent.click(await screen.findByRole('button', { name: 'Analysis history' }))

    expect(await screen.findByText('Analysis history unavailable.')).toBeInTheDocument()
  })

  it('opens analysis history directly from the persisted hash without an active analysis', async () => {
    window.location.hash = '#analyses'

    render(<App />)

    expect(await screen.findByRole('heading', { name: 'Analysis history' })).toBeInTheDocument()
    expect(screen.getByText('No analyses')).toBeInTheDocument()
  })

  it('renders persisted KPI columns, opens a row, and deletes only after confirmation', async () => {
    configureCompletedRun()
    fixtures.getAnalysisHistory.mockResolvedValue({ items: [historyItem], total: 1, limit: 20, offset: 0 })
    fixtures.deleteAnalysis.mockResolvedValue(undefined)
    render(<App />)
    fireEvent.submit(
      screen.getByRole('button', { name: 'Analyze repository' }).closest('form')!,
      { preventDefault: () => undefined },
    )
    fireEvent.click(await screen.findByRole('button', { name: 'Analysis history' }))
    expect(await screen.findByRole('columnheader', { name: 'Repository' })).toBeInTheDocument()
    expect(screen.getByRole('rowheader', { name: /demo/ })).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: '0.80 (high)' })).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: '1' })).toBeInTheDocument()
    expect(screen.getByText(/2026/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('link', { name: /demo/ }))
    expect(window.location.hash).toBe('#overview')
    fireEvent.click(await screen.findByRole('button', { name: 'Analysis history' }))
    fireEvent.click(screen.getByRole('button', { name: 'Delete analysis demo' }))
    expect(screen.getByRole('dialog', { name: 'Delete analysis?' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('dialog', { name: 'Delete analysis?' }).querySelector('button')!)
    expect(fixtures.deleteAnalysis).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'Delete analysis demo' }))
    const confirmation = screen.getByRole('dialog', { name: 'Delete analysis?' })
    fireEvent.click(within(confirmation).getByRole('button', { name: 'Delete analysis' }))
    await waitFor(() => expect(fixtures.deleteAnalysis).toHaveBeenCalledWith('analysis-1'))
  })

  it('shows total hotspots in Quality Gate while preserving new-hotspot evidence', async () => {
    configureCompletedRun()
    fixtures.getAnalysisSummary.mockResolvedValue({
      ...summary,
      summary: {
        ...summary.summary,
        hotspot_count: 11,
        quality_gate: {
          ...summary.summary.quality_gate,
          observed: { ...summary.summary.quality_gate.observed, new_hotspots: 0 },
        },
      },
    })
    render(<App />)
    fireEvent.submit(
      screen.getByRole('button', { name: 'Analyze repository' }).closest('form')!,
      { preventDefault: () => undefined },
    )
    fireEvent.click(await screen.findByRole('button', { name: 'Quality gate' }))
    expect(screen.getAllByText('Hotspots').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('11')).toBeInTheDocument()
  })

  it('selects multiple history rows and deletes only after the React confirmation', async () => {
    configureCompletedRun()
    fixtures.getAnalysisHistory.mockResolvedValue({
      items: [historyItem, { ...historyItem, analysis_id: 'analysis-2', repository_name: 'other' }],
      total: 2,
      limit: 20,
      offset: 0,
    })
    fixtures.deleteAnalysis.mockResolvedValue(undefined)
    render(<App />)
    fireEvent.submit(
      screen.getByRole('button', { name: 'Analyze repository' }).closest('form')!,
      { preventDefault: () => undefined },
    )
    fireEvent.click(await screen.findByRole('button', { name: 'Analysis history' }))

    fireEvent.click(screen.getByRole('checkbox', { name: 'Select analysis demo' }))
    expect(screen.getByRole('button', { name: 'Delete selected (1)' })).toBeEnabled()
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select all analyses' }))
    expect(screen.getByRole('button', { name: 'Delete selected (2)' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: 'Delete selected (2)' }))
    const dialog = screen.getByRole('dialog', { name: 'Delete selected analyses?' })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Delete analyses' }))
    await waitFor(() => expect(fixtures.deleteAnalysis).toHaveBeenCalledTimes(2))
    expect(fixtures.deleteAnalysis).toHaveBeenCalledWith('analysis-1')
    expect(fixtures.deleteAnalysis).toHaveBeenCalledWith('analysis-2')
  })

  it('keeps failed bulk deletions selected and reports the failure', async () => {
    configureCompletedRun()
    fixtures.getAnalysisHistory.mockResolvedValue({
      items: [
        { ...historyItem, analysis_id: 'analysis-2', repository_name: 'other' },
        { ...historyItem, analysis_id: 'analysis-3', repository_name: 'third' },
      ],
      total: 2,
      limit: 20,
      offset: 0,
    })
    fixtures.deleteAnalysis.mockImplementation(async (id: string) => {
      if (id === 'analysis-2') throw new Error('Conflict')
    })
    render(<App />)
    fireEvent.submit(
      screen.getByRole('button', { name: 'Analyze repository' }).closest('form')!,
      { preventDefault: () => undefined },
    )
    fireEvent.click(await screen.findByRole('button', { name: 'Analysis history' }))
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select all analyses' }))
    fireEvent.click(screen.getByRole('button', { name: 'Delete selected (2)' }))
    const dialog = screen.getByRole('dialog', { name: 'Delete selected analyses?' })
    fireEvent.click(
      within(dialog).getByRole('button', { name: 'Delete analyses' }),
    )
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('1 analysis could not be deleted.'))
    expect(screen.getByRole('checkbox', { name: 'Select analysis other' })).toBeChecked()
  })

  it('loads persisted Setup configuration as part of the initial App startup', async () => {
    fixtures.getLlmConfiguration.mockResolvedValue({
      enabled: true,
      provider: 'openai',
      model: 'gpt-5',
      api_key_configured: true,
      available_models: ['gpt-5', 'gpt-4o'],
      reasoning_effort: 'high',
      reasoning_efforts_by_model: { 'gpt-5': ['minimal', 'low', 'medium', 'high'] },
    })

    render(<App />)

    await waitFor(() => {
      expect(fixtures.getLlmConfiguration).toHaveBeenCalledOnce()
      expect(fixtures.getLlmProviders).toHaveBeenCalledOnce()
    })
    expect(screen.queryByLabelText('Provider')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Setup' }))
    expect(await screen.findByLabelText('Enable LLM enrichment')).toBeChecked()
    expect(screen.getByLabelText('Provider')).toHaveValue('openai')
    expect(screen.getByLabelText('Model')).toHaveValue('gpt-5')
    expect(screen.getByLabelText('Reasoning effort')).toHaveValue('high')
    expect(screen.getByLabelText('API key')).toHaveAttribute('placeholder', 'Stored key (leave blank to keep)')
  })

  it('opens Setup without an analysis and keeps LLM controls disabled until enabled', async () => {
    fixtures.getLlmConfiguration.mockResolvedValue({ enabled: false, provider: 'openai', model: 'gpt-5-mini', api_key_configured: false })
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Setup' }))
    expect(await screen.findByRole('heading', { name: 'Setup' })).toBeInTheDocument()
    const provider = await screen.findByLabelText('Provider')
    const model = screen.getByLabelText('Model')
    const apiKey = screen.getByLabelText('API key')
    const providerField = provider.closest('.form-field')
    const modelField = model.closest('.form-field')
    const apiKeyField = apiKey.closest('.form-field')
    expect(providerField).toHaveClass('form-field')
    expect(modelField).toHaveClass('form-field')
    expect(providerField?.parentElement).toHaveClass('setup-fields')
    expect(modelField?.parentElement).toBe(providerField?.parentElement)
    expect(apiKeyField).toHaveClass('form-field-wide')
    expect(screen.getByLabelText('Enable LLM enrichment').closest('label')).toHaveClass('form-checkbox')
    expect(screen.getByRole('button', { name: 'Save LLM configuration' }).closest('.form-actions')).toContainElement(
      screen.getByRole('button', { name: 'Save LLM configuration' }),
    )
    expect(apiKey).toHaveAttribute('placeholder', '')
    expect(screen.queryByPlaceholderText('Stored key (leave blank to keep)')).not.toBeInTheDocument()
    expect(provider).toBeDisabled()
    expect(apiKey).toBeDisabled()
    fireEvent.click(screen.getByLabelText('Enable LLM enrichment'))
    expect(provider).toBeEnabled()
    expect(screen.getByLabelText('API key')).toBeEnabled()
    expect(model).toBeDisabled()
  })

  it('updates and saves the enabled Setup configuration', async () => {
    fixtures.getLlmConfiguration.mockResolvedValue({
      enabled: true,
      provider: 'openai',
      model: 'gpt-4o-mini',
      api_key_configured: true,
      available_models: ['gpt-4o-mini', 'gpt-4o'],
    })
    fixtures.saveLlmConfiguration.mockResolvedValue({
      enabled: true,
      provider: 'openai',
      model: 'gpt-4o',
      api_key_configured: true,
      available_models: ['gpt-4o-mini', 'gpt-4o'],
    })
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Setup' }))

    const provider = await screen.findByLabelText('Provider')
    const model = screen.getByLabelText('Model')
    const apiKey = screen.getByLabelText('API key')
    expect(screen.getByPlaceholderText('Stored key (leave blank to keep)')).toBe(apiKey)
    expect(within(model).getByRole('option', { name: 'gpt-4o' })).toBeInTheDocument()

    fireEvent.change(apiKey, { target: { value: 'secret' } })
    fireEvent.change(provider, { target: { value: 'anthropic' } })
    expect(model).toBeDisabled()
    expect(apiKey).toHaveValue('')
    fixtures.saveLlmConfiguration.mockClear()
    fireEvent.click(screen.getByRole('button', { name: 'Save LLM configuration' }))
    await waitFor(() => expect(fixtures.saveLlmConfiguration).toHaveBeenCalledWith({ enabled: true, provider: 'anthropic' }))
    fireEvent.change(provider, { target: { value: 'openai' } })
    expect(model).toHaveValue('gpt-4o-mini')
    fireEvent.change(model, { target: { value: 'gpt-4o' } })
    fireEvent.change(apiKey, { target: { value: 'secret' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save LLM configuration' }))

    await waitFor(() => expect(fixtures.saveLlmConfiguration).toHaveBeenCalledWith({
      enabled: true,
      provider: 'openai',
      model: 'gpt-4o',
      api_key: 'secret',
    }))
    expect(await screen.findByRole('status')).toHaveTextContent('LLM configuration saved.')
  })

  it('updates effort choices with the selected model and saves the effort', async () => {
    fixtures.getLlmConfiguration.mockResolvedValue({
      enabled: true,
      provider: 'openai',
      model: 'gpt-5',
      api_key_configured: true,
      available_models: ['gpt-5', 'gpt-4o'],
      reasoning_effort: null,
      reasoning_efforts_by_model: { 'gpt-5': ['minimal', 'low', 'medium', 'high'], 'gpt-4o': [] },
    })
    fixtures.saveLlmConfiguration.mockResolvedValue({
      enabled: true,
      provider: 'openai',
      model: 'gpt-5',
      api_key_configured: true,
      available_models: ['gpt-5', 'gpt-4o'],
      reasoning_effort: 'high',
      reasoning_efforts_by_model: { 'gpt-5': ['minimal', 'low', 'medium', 'high'], 'gpt-4o': [] },
    })
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Setup' }))
    const effort = await screen.findByLabelText('Reasoning effort')
    expect(effort).toBeEnabled()
    expect(within(effort).getByRole('option', { name: 'high' })).toBeInTheDocument()
    fireEvent.change(effort, { target: { value: 'high' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save LLM configuration' }))
    await waitFor(() => expect(fixtures.saveLlmConfiguration).toHaveBeenCalledWith(expect.objectContaining({ reasoning_effort: 'high' })))
    const model = screen.getByLabelText('Model')
    fireEvent.change(model, { target: { value: 'gpt-4o' } })
    expect(effort).toHaveValue('')
    expect(effort).toBeDisabled()
  })

  it('shows the saving state and clears the API key after saving', async () => {
    const pending = deferred<{
      enabled: boolean
      provider: string
      model: string
      api_key_configured: boolean
      available_models: string[]
    }>()
    fixtures.getLlmConfiguration.mockResolvedValue({
      enabled: true,
      provider: 'openai',
      model: 'gpt-4o',
      api_key_configured: false,
      available_models: ['gpt-4o'],
    })
    fixtures.saveLlmConfiguration.mockReturnValue(pending.promise)
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Setup' }))

    const apiKey = await screen.findByLabelText('API key')
    fireEvent.change(apiKey, { target: { value: 'secret' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save LLM configuration' }))
    expect(screen.getByRole('button', { name: 'Saving…' })).toBeDisabled()
    pending.resolve({
      enabled: true,
      provider: 'openai',
      model: 'gpt-4o',
      api_key_configured: true,
      available_models: ['gpt-4o'],
    })
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save LLM configuration' })).toBeEnabled())
    expect(apiKey).toHaveValue('')
  })

  it('shows a fallback message when saving fails with a non-error value', async () => {
    fixtures.getLlmConfiguration.mockResolvedValue({
      enabled: true,
      provider: 'openai',
      model: 'gpt-4o',
      api_key_configured: false,
      available_models: ['gpt-4o'],
    })
    fixtures.saveLlmConfiguration.mockRejectedValue('Save failed')
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Setup' }))
    await screen.findByLabelText('API key')
    fireEvent.click(screen.getByRole('button', { name: 'Save LLM configuration' }))

    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Unable to save LLM configuration.'))
  })

  it('shows a load error when Setup configuration cannot be fetched', async () => {
    fixtures.getLlmConfiguration.mockRejectedValue('Configuration unavailable')
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Setup' }))

    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Unable to load LLM configuration.'))
  })

  it('keeps Setup controls at safe defaults while configuration is loading', async () => {
    const configuration = deferred<{
      enabled: boolean
      provider: string
      model: string
      api_key_configured: boolean
      available_models: string[]
    }>()
    const providers = deferred<{ providers: readonly { id: string; label: string }[] }>()
    fixtures.getLlmConfiguration.mockReturnValue(configuration.promise)
    fixtures.getLlmProviders.mockReturnValue(providers.promise)
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Setup' }))

    const provider = await screen.findByLabelText('Provider')
    expect(provider).toBeDisabled()
    expect(screen.getByLabelText('API key')).toHaveValue('')
    expect(screen.getByRole('button', { name: 'Save LLM configuration' })).toBeDisabled()

    configuration.resolve({
      enabled: true,
      provider: 'openai',
      model: 'gpt-4o',
      api_key_configured: false,
      available_models: ['gpt-4o'],
    })
    providers.resolve({ providers: LLM_PROVIDERS })
    await waitFor(() => expect(provider).toBeEnabled())
    expect(screen.getByRole('button', { name: 'Save LLM configuration' })).toBeEnabled()
  })
})
describe('completed analysis result loading', () => {
  it('filters findings by severity and type', async () => {
    configureCompletedRun()
    fixtures.getAnalysisFindings.mockResolvedValue(filterFindings)
    fixtures.getAnalysisHotspots.mockResolvedValue([insight])
    fixtures.getAnalysisFiles.mockResolvedValue({ items: [insight], total: 1, limit: 100, offset: 0 })

    render(<App />)
    fireEvent.submit(screen.getByRole('button', { name: 'Analyze repository' }).closest('form')!, {
      preventDefault: () => undefined,
    })
    fireEvent.click(await screen.findByRole('button', { name: 'Findings' }))
    await waitFor(() => expect(screen.getByText('Findings (3)')).toBeInTheDocument())

    expect(screen.queryByRole('checkbox', { name: 'Critical' })).not.toBeInTheDocument()
    const filterButton = screen.getByRole('button', { name: 'Filter' })
    filterButton.focus()
    fireEvent.click(filterButton)
    const firstDialog = screen.getByRole('dialog', { name: 'Filter findings' })
    fireEvent.click(within(firstDialog).getByRole('checkbox', { name: 'Critical' }))
    expect(screen.getByText('Avoid this pattern.')).toBeInTheDocument()
    fireEvent.keyDown(firstDialog, { key: 'Escape' })
    expect(screen.queryByRole('dialog', { name: 'Filter findings' })).not.toBeInTheDocument()
    expect(filterButton).toHaveFocus()
    expect(screen.queryByLabelText('Applied filters')).not.toBeInTheDocument()

    fireEvent.click(filterButton)
    const cancelledDialog = screen.getByRole('dialog', { name: 'Filter findings' })
    fireEvent.click(within(cancelledDialog).getByRole('checkbox', { name: 'Critical' }))
    fireEvent.click(within(cancelledDialog).getByRole('button', { name: 'Cancel' }))
    expect(screen.getByText('Avoid this pattern.')).toBeInTheDocument()
    expect(screen.queryByLabelText('Applied filters')).not.toBeInTheDocument()

    fireEvent.click(filterButton)
    const dialog = screen.getByRole('dialog', { name: 'Filter findings' })
    fireEvent.click(within(dialog).getByRole('checkbox', { name: 'Critical' }))
    fireEvent.click(within(dialog).getByRole('checkbox', { name: 'Security' }))
    fireEvent.click(within(dialog).getByRole('button', { name: 'Apply' }))
    expect(filterButton).toHaveFocus()

    const appliedFilters = screen.getByLabelText('Applied filters')
    expect(within(appliedFilters).getByText('Critical')).toBeInTheDocument()
    expect(within(appliedFilters).getByText('Security')).toBeInTheDocument()
    expect(screen.getByText('Critical security issue.')).toBeInTheDocument()
    expect(screen.queryByText('Avoid this pattern.')).not.toBeInTheDocument()
    expect(screen.queryByText('Informational quality issue.')).not.toBeInTheDocument()

    fireEvent.click(filterButton)
    const clearDialog = screen.getByRole('dialog', { name: 'Filter findings' })
    fireEvent.click(within(clearDialog).getByRole('button', { name: 'Clear filters' }))
    fireEvent.click(within(clearDialog).getByRole('button', { name: 'Apply' }))
    expect(screen.queryByLabelText('Applied filters')).not.toBeInTheDocument()
    expect(screen.getByText('Avoid this pattern.')).toBeInTheDocument()
    expect(screen.getByText('Informational quality issue.')).toBeInTheDocument()
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
    fireEvent.click(screen.getByRole('button', { name: 'Filter' }))
    const dialog = screen.getByRole('dialog', { name: 'Filter findings' })
    fireEvent.click(within(dialog).getByRole('checkbox', { name: 'Critical' }))
    expect(exportButton).toBeEnabled()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Apply' }))
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
    const secondInsight = {
      ...insight,
      path: 'src/other.py',
      hotspot_score: 0.4,
      risk: { ...insight.risk!, score: 0.4, category: 'medium' },
      metrics: { complexity: 0.4, coupling: 0.3 },
    }
    fixtures.getAnalysisFindings.mockResolvedValue([finding])
    fixtures.getAnalysisHotspots.mockResolvedValue([insight, secondInsight])
    fixtures.getAnalysisFiles.mockResolvedValue({ items: [insight, secondInsight], total: 2, limit: 100, offset: 0 })
    fixtures.getAnalysisFileDetail.mockImplementation(
      async (_id: string, path: string) => ({
        ...(path === insight.path ? insight : secondInsight),
        findings: path === insight.path ? [finding] : [],
      }),
    )

    render(<App />)
    fireEvent.submit(
      screen.getByRole('button', { name: 'Analyze repository' }).closest('form')!,
      { preventDefault: () => undefined },
    )
    fireEvent.click(await screen.findByRole('button', { name: 'Hotspots' }))
    await waitFor(() => expect(screen.getByText('Hotspots (2)')).toBeInTheDocument())

    expect(screen.getByRole('button', { name: 'Export hotspots (.md)' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: 'Filter' }))
    const dialog = screen.getByRole('dialog', { name: 'Filter hotspots' })
    fireEvent.click(within(dialog).getByRole('checkbox', { name: 'High' }))
    expect(screen.getByText('Hotspots (2)')).toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Apply' }))
    expect(screen.getByText('Hotspots (1 of 2)')).toBeInTheDocument()
    expect(within(screen.getByLabelText('Applied filters')).getByText('High')).toBeInTheDocument()
    expect(screen.queryByText('src/other.py')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Risk/ }))
    expect(screen.getByRole('columnheader', { name: /Risk/ })).toHaveAttribute('aria-sort', 'ascending')
  })

  it('exports visible hotspots, fetches related details, and tolerates one detail failure', async () => {
    configureCompletedRun()
    const secondInsight = {
      ...insight,
      path: 'src/other.py',
      hotspot_score: 0.4,
      risk: { ...insight.risk!, score: 0.4, category: 'medium' },
      metrics: { complexity: 0.4 },
    }
    fixtures.getAnalysisFindings.mockResolvedValue([finding])
    fixtures.getAnalysisHotspots.mockResolvedValue([insight, secondInsight])
    fixtures.getAnalysisFiles.mockResolvedValue({ items: [insight, secondInsight], total: 2, limit: 100, offset: 0 })
    fixtures.getAnalysisFileDetail.mockImplementation(async (_id: string, path: string) => {
      if (path === secondInsight.path) throw new Error('partial detail failure')
      return { ...insight, findings: [finding] }
    })

    render(<App />)
    fireEvent.change(screen.getByLabelText('Repository URL'), { target: { value: 'https://github.com/acme/demo' } })
    fireEvent.submit(
      screen.getByRole('button', { name: 'Analyze repository' }).closest('form')!,
      { preventDefault: () => undefined },
    )
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
    expect(fixtures.getAnalysisFileDetail).toHaveBeenCalledWith(
      'analysis-1',
      'src/main.py',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )

    fireEvent.click(screen.getByRole('button', { name: 'Quality gate' }))
    expect(screen.getByText('Risk score')).toBeInTheDocument()
    expect(screen.getByText('0.80')).toBeInTheDocument()
  })

  it('renders bounded source context, highlighted range, evidence, and remediation', async () => {
    configureCompletedRun()
    fixtures.getAnalysisFindings.mockResolvedValue(contextualFindings)
    fixtures.getAnalysisHotspots.mockResolvedValue([insight])
    fixtures.getAnalysisFiles.mockResolvedValue({ items: [insight], total: 1, limit: 100, offset: 0 })
    fixtures.getAnalysisFileDetail.mockResolvedValue({ ...insight, findings: contextualFindings })

    render(<App />)
    fireEvent.submit(
      screen.getByRole('button', { name: 'Analyze repository' }).closest('form')!,
      { preventDefault: () => undefined },
    )
    fireEvent.click(await screen.findByRole('button', { name: 'File detail' }))
    await waitFor(() => expect(screen.getByRole('button', { name: /PY001/ })).toBeInTheDocument())
    expect(screen.queryByText('eval(x)')).not.toBeInTheDocument()
    expect(screen.getByText('Unsafe call')).toBeInTheDocument()
    expect(screen.getByText('Use a safe parser.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /PY001/ }))
    expect(screen.getByText('eval(x)')).toBeInTheDocument()
    expect(screen.getByText('eval(x)').closest('.source-line')).toHaveClass('source-line-highlight')
  })

  it('hides source context again after selecting another file', async () => {
    configureCompletedRun()
    fixtures.getAnalysisFindings.mockResolvedValue(contextualFindings)
    fixtures.getAnalysisHotspots.mockResolvedValue([insight, alternateInsight])
    fixtures.getAnalysisFiles.mockResolvedValue({ items: [insight, alternateInsight], total: 2, limit: 100, offset: 0 })
    fixtures.getAnalysisFileDetail.mockImplementation(async (_id: string, path: string) => ({
      ...(path === insight.path ? insight : alternateInsight),
      findings: contextualFindings,
    }))

    render(<App />)
    fireEvent.submit(
      screen.getByRole('button', { name: 'Analyze repository' }).closest('form')!,
      { preventDefault: () => undefined },
    )
    fireEvent.click(await screen.findByRole('button', { name: 'File detail' }))
    const findingButton = await screen.findByRole('button', { name: /PY001/ })
    fireEvent.click(findingButton)
    expect(screen.getByText('eval(x)')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('File'), { target: { value: alternateInsight.path } })
    await waitFor(() => expect(screen.getByRole('heading', { name: alternateInsight.path })).toBeInTheDocument())
    expect(screen.queryByText('eval(x)')).not.toBeInTheDocument()
  })

  it('shows source context for only one finding at a time', async () => {
    configureCompletedRun()
    fixtures.getAnalysisFindings.mockResolvedValue(multipleContextualFindings)
    fixtures.getAnalysisHotspots.mockResolvedValue([insight])
    fixtures.getAnalysisFiles.mockResolvedValue({ items: [insight], total: 1, limit: 100, offset: 0 })
    fixtures.getAnalysisFileDetail.mockResolvedValue({ ...insight, findings: multipleContextualFindings })

    render(<App />)
    fireEvent.submit(
      screen.getByRole('button', { name: 'Analyze repository' }).closest('form')!,
      { preventDefault: () => undefined },
    )
    fireEvent.click(await screen.findByRole('button', { name: 'File detail' }))
    const firstFinding = await screen.findByRole('button', { name: /PY001/ })
    const secondFinding = screen.getByRole('button', { name: /PY002/ })

    fireEvent.click(firstFinding)
    expect(screen.getByText('eval(x)')).toBeInTheDocument()
    expect(screen.queryByText('danger()')).not.toBeInTheDocument()

    fireEvent.click(secondFinding)
    expect(screen.queryByText('eval(x)')).not.toBeInTheDocument()
    expect(screen.getByText('danger()')).toBeInTheDocument()
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

  it('configures quality thresholds, imports a Sonar profile, and navigates to evidence', async () => {
    configureCompletedRun()
    fixtures.createAnalysis.mockResolvedValue({ analysis_id: 'analysis-1', status: 'queued', project_id: 'project-1' })
    fixtures.getAnalysisFindings.mockResolvedValue([finding])
    fixtures.getAnalysisHotspots.mockResolvedValue([insight])
    fixtures.getAnalysisFiles.mockResolvedValue({ items: [insight], total: 1, limit: 100, offset: 0 })
    fixtures.getProjects.mockResolvedValue({
      items: [
        {
          project_id: 'project-1',
          repository_url: 'https://github.com/acme/demo',
          name: 'demo',
          created_at: '',
          updated_at: '',
        },
      ],
    })
    fixtures.getQualityPolicy.mockResolvedValue({
      version: 1,
      configured: false,
      max_new_critical_findings: null,
      max_risk_score: null,
      max_new_hotspots: null,
      profiles: [],
    })
    fixtures.saveQualityPolicy.mockResolvedValue({
      version: 2,
      configured: true,
      max_new_critical_findings: 1,
      max_risk_score: 0.5,
      max_new_hotspots: 2,
      profiles: [],
    })
    fixtures.importQualityProfile.mockResolvedValue({
      language: 'python',
      profile_name: 'py',
      mapped: 1,
      unsupported: [],
      invalid: [],
    })
    render(<App />)
    fireEvent.change(screen.getByLabelText('Repository URL'), { target: { value: 'https://github.com/acme/demo' } })
    fireEvent.submit(
      screen.getByRole('button', { name: 'Analyze repository' }).closest('form')!,
      { preventDefault: () => undefined },
    )
    fireEvent.click(await screen.findByRole('button', { name: 'Quality gate' }))
    await waitFor(() => expect(screen.getByLabelText('Maximum risk score')).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText('Maximum risk score'), { target: { value: '0.5' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save quality gate' }))
    await waitFor(() => expect(fixtures.saveQualityPolicy).toHaveBeenCalled())
    fireEvent.change(screen.getByLabelText('Import SonarQube profile XML'), {
      target: { files: [new File(['<profile />'], 'profile.xml', { type: 'application/xml' })] },
    })
    await waitFor(() => expect(screen.getByText('Imported 1 rules; 0 unsupported.')).toBeInTheDocument())
    expect(fixtures.importQualityProfile).toHaveBeenCalledWith('project-1', '<profile />')
    fixtures.importQualityProfile.mockRejectedValueOnce(new Error('Import failed by test'))
    fireEvent.change(screen.getByLabelText('Import SonarQube profile XML'), {
      target: { files: [new File(['<invalid />'], 'invalid.xml', { type: 'application/xml' })] },
    })
    await waitFor(() => expect(screen.getByText('Import failed by test')).toBeInTheDocument())
    fixtures.importQualityProfile.mockRejectedValueOnce('invalid profile')
    fireEvent.change(screen.getByLabelText('Import SonarQube profile XML'), {
      target: { files: [new File(['<broken />'], 'broken.xml', { type: 'application/xml' })] },
    })
    await waitFor(() => expect(screen.getByText('Import failed.')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Open findings' }))
    expect(window.location.hash).toBe('#findings')
  })
})
