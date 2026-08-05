import { afterEach, describe, expect, it, vi } from 'vitest'
import { createAnalysis, getAnalysisStatus, getAnalysisSummary } from './api'

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
})
