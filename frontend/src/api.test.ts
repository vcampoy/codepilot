import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  createAnalysis,
  getAnalysisFileDetail,
  getAnalysisFiles,
  getAnalysisFindings,
  getAnalysisHotspots,
  getAnalysisStatus,
  getAnalysisSummary,
  getLlmConfiguration,
  saveLlmConfiguration,
} from './api'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('analysis API client', () => {
  it('submits a repository URL as JSON', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ analysis_id: 'analysis-1', status: 'queued' }), {
        status: 202,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(createAnalysis('https://github.com/acme/project')).resolves.toEqual({
      analysis_id: 'analysis-1',
      status: 'queued',
    })
    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/api/v1/analyses',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ repository_url: 'https://github.com/acme/project' }),
      }),
    )
  })

  it('encodes analysis identifiers and exposes API errors', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ message: 'Analysis is unavailable.' }), { status: 404 }),
      ),
    )

    await expect(getAnalysisStatus('analysis/with spaces')).rejects.toThrow('Analysis is unavailable.')
    expect(fetch).toHaveBeenCalledWith(
      'http://localhost:8000/api/v1/analyses/analysis%2Fwith%20spaces',
      expect.any(Object),
    )
  })

  it('requests the summary endpoint for completed analysis data', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ analysis_id: 'analysis-1', status: 'completed', summary: null }), {
          status: 200,
        }),
      ),
    )

    await expect(getAnalysisSummary('analysis-1')).resolves.toMatchObject({
      analysis_id: 'analysis-1',
      status: 'completed',
    })
    expect(fetch).toHaveBeenCalledWith(
      'http://localhost:8000/api/v1/analyses/analysis-1/summary',
      expect.any(Object),
    )
  })

  it('requests findings for the selected analysis', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify([{ analyzer: 'python.ruff', path: 'main.py' }]), {
          status: 200,
        }),
      ),
    )

    await expect(getAnalysisFindings('analysis-1')).resolves.toEqual([
      { analyzer: 'python.ruff', path: 'main.py' },
    ])
    expect(fetch).toHaveBeenCalledWith(
      'http://localhost:8000/api/v1/analyses/analysis-1/findings',
      expect.any(Object),
    )
  })

  it('requests hotspots and file detail for the selected analysis', async () => {
    const calls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      calls.push(url)
      return new Response(JSON.stringify(url.includes('/hotspots') ? [] : { path: 'src/a.py' }), { status: 200 })
    }))

    await expect(getAnalysisHotspots('analysis-1')).resolves.toEqual([])
    await expect(getAnalysisFileDetail('analysis-1', 'src/a.py')).resolves.toEqual({ path: 'src/a.py' })
    expect(calls).toEqual([
      'http://localhost:8000/api/v1/analyses/analysis-1/hotspots?limit=20',
      'http://localhost:8000/api/v1/analyses/analysis-1/files/detail?path=src%2Fa.py',
    ])
  })

  it('requests the paginated file insight catalog', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ items: [], total: 0, limit: 100, offset: 0 }), { status: 200 }),
      ),
    )

    await expect(getAnalysisFiles('analysis-1')).resolves.toEqual({
      items: [],
      total: 0,
      limit: 100,
      offset: 0,
    })
    expect(fetch).toHaveBeenCalledWith(
      'http://localhost:8000/api/v1/analyses/analysis-1/files?limit=100&offset=0',
      expect.any(Object),
    )
  })

  it('saves and reads secret-safe LLM configuration', async () => {
    const fetchMock = vi.fn().mockImplementation(
      () =>
        new Response(
          JSON.stringify({
            enabled: true,
            provider: 'openai',
            model: 'gpt-test',
            api_key_configured: true,
          }),
          { status: 200 },
        ),
    )
    vi.stubGlobal('fetch', fetchMock)
    await expect(saveLlmConfiguration({ enabled: true, provider: 'openai', model: 'gpt-test', api_key: 'sk-test' })).resolves.toMatchObject({ api_key_configured: true })
    await expect(getLlmConfiguration()).resolves.toMatchObject({ provider: 'openai' })
    expect(fetchMock.mock.calls[0][0]).toBe('http://localhost:8000/api/v1/settings/llm')
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: 'PUT' })
  })
})
