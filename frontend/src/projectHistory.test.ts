import { describe, expect, it, vi } from 'vitest'

describe('project history API contract', () => {
  it('exposes project catalog and run endpoints', async () => {
    vi.resetModules()
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ items: [], total: 0, limit: 20, offset: 0 }) })
    vi.stubGlobal('fetch', fetchMock)
    const api = await import('./api')
    await api.getProjects()
    await api.getProjectAnalyses('project-1')
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      'http://localhost:8000/api/v1/projects?limit=20&offset=0',
      'http://localhost:8000/api/v1/projects/project-1/analyses?limit=20&offset=0',
    ])
  })
})
