import { describe, expect, it, vi } from 'vitest'

const EMPTY_HISTORY_RESPONSE = { items: [], total: 0, limit: 20, offset: 0 } as const

describe('project history API contract', () => {
  it('exposes project catalog and run endpoints', async () => {
    vi.resetModules()
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => EMPTY_HISTORY_RESPONSE })
    vi.stubGlobal('fetch', fetchMock)
    const api = await import('./api')
    await api.getProjects()
    await api.getProjectAnalyses('project-1')
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      'http://localhost:8000/api/v1/projects?limit=20&offset=0',
      'http://localhost:8000/api/v1/projects/project-1/analyses?limit=20&offset=0',
    ])
  })

  it('requests the flat history endpoint and deletes an encoded analysis', async () => {
    vi.resetModules()
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => EMPTY_HISTORY_RESPONSE })
    vi.stubGlobal('fetch', fetchMock)
    const api = await import('./api')
    await api.getAnalysisHistory()
    await api.deleteAnalysis('analysis/1')
    expect(fetchMock.mock.calls.map(([url, init]) => [url, init?.method])).toEqual([
      ['http://localhost:8000/api/v1/analyses/history?limit=20&offset=0', undefined],
      ['http://localhost:8000/api/v1/analyses/analysis%2F1', 'DELETE'],
    ])
  })
})
