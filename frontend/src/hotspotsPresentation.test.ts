import { describe, expect, it } from 'vitest'
import type { FileInsight } from './api'
import {
  HOTSPOT_RISKS,
  filterHotspots,
  sortHotspots,
  toggleHotspotSort,
  hotspotComponentCount,
  type HotspotSort,
} from './hotspotsPresentation'

const hotspot = (path: string, score: number, risk: string | null, metrics: Record<string, number>): FileInsight => ({
  path,
  hotspot_score: score,
  risk: risk ? { score, category: risk, version: '1.0', components: metrics, weights: metrics } : null,
  metrics,
})

const SORTED_MISSING_HOTSPOT_PATHS = ['known.ts', 'missing.ts'] as const

describe('hotspots presentation', () => {
  it('filters by risk category and keeps input immutable', () => {
    const hotspots = [
      hotspot('src/low.py', 0.2, 'low', { complexity: 0.2 }),
      hotspot('src/high.py', 0.8, 'high', { complexity: 0.8 }),
      hotspot('src/missing.py', 0.1, null, {}),
    ] as const

    expect(filterHotspots(hotspots, { risks: ['high'] }).map((item) => item.path)).toEqual(['src/high.py'])
    expect(filterHotspots(hotspots, { risks: ['unavailable'] }).map((item) => item.path)).toEqual(['src/missing.py'])
    expect(hotspots.map((item) => item.path)).toEqual(['src/low.py', 'src/high.py', 'src/missing.py'])
    expect(HOTSPOT_RISKS).toContain('critical')
  })

  it.each([
    ['file', 'asc', ['a.ts', 'b.ts']],
    ['hotspot_score', 'desc', ['b.ts', 'a.ts']],
    ['risk', 'asc', ['a.ts', 'b.ts']],
    ['components', 'desc', ['b.ts', 'a.ts']],
  ] as const)('sorts by %s in %s order', (column, direction, expected) => {
    const hotspots = [
      hotspot('b.ts', 0.8, 'high', { complexity: 0.8, coupling: 0.2 }),
      hotspot('a.ts', 0.2, 'low', { complexity: 0.2 }),
    ] as const
    expect(sortHotspots(hotspots, { column, direction }).map((item) => item.path)).toEqual(expected)
  })

  it('sorts missing risk last and counts components', () => {
    const hotspots = [hotspot('missing.ts', 0.9, null, {}), hotspot('known.ts', 0.1, 'low', { x: 1 })] as const
    expect(
      sortHotspots(hotspots, { column: 'risk', direction: 'asc' }).map((item) => item.path),
    ).toEqual(SORTED_MISSING_HOTSPOT_PATHS)
    expect(
      sortHotspots(hotspots, { column: 'risk', direction: 'desc' }).map((item) => item.path),
    ).toEqual(SORTED_MISSING_HOTSPOT_PATHS)
    expect(hotspotComponentCount(hotspots[0])).toBe(0)
  })

  it('keeps hotspots without components last in both directions', () => {
    const hotspots = [hotspot('missing.ts', 0.9, 'high', {}), hotspot('known.ts', 0.1, 'low', { x: 1 })] as const
    expect(
      sortHotspots(hotspots, { column: 'components', direction: 'asc' }).map((item) => item.path),
    ).toEqual(SORTED_MISSING_HOTSPOT_PATHS)
    expect(
      sortHotspots(hotspots, { column: 'components', direction: 'desc' }).map((item) => item.path),
    ).toEqual(SORTED_MISSING_HOTSPOT_PATHS)
  })

  it('toggles active sort direction and starts ascending for a new column', () => {
    const initial: HotspotSort = { column: 'hotspot_score', direction: 'desc' }
    expect(toggleHotspotSort(initial, 'hotspot_score')).toEqual({ column: 'hotspot_score', direction: 'asc' })
    expect(toggleHotspotSort(initial, 'file')).toEqual({ column: 'file', direction: 'asc' })
  })
})
