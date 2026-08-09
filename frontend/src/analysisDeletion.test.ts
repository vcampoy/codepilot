import { describe, expect, it, vi } from 'vitest'
import { deleteAnalyses } from './analysisDeletion'

const ANALYSIS_IDS = ['analysis-1', 'analysis-2', 'analysis-3'] as const

describe('analysis deletion', () => {
  it('attempts every selected analysis and separates successes from failures', async () => {
    const deleteAnalysis = vi.fn(async (id: string) => {
      if (id === 'analysis-2') throw new Error('Conflict')
    })

    await expect(deleteAnalyses(ANALYSIS_IDS, deleteAnalysis)).resolves.toEqual({
      deleted: ['analysis-1', 'analysis-3'],
      failed: [{ id: 'analysis-2', error: expect.any(Error) }],
    })
    expect(deleteAnalysis).toHaveBeenCalledTimes(3)
  })
})
