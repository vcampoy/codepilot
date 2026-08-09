import { describe, expect, it } from 'vitest'
import type { FileDetail, FileInsight } from './api'
import { createHotspotsMarkdownExport } from './hotspotsExport'

const EXPORTED_AT = new Date(2026, 7, 9, 10, 11, 12)
const hotspots: readonly FileInsight[] = [
  {
    path: 'src/main.py',
    hotspot_score: 0.91,
    risk: { score: 0.88, category: 'critical', version: '1.0', components: { complexity: 0.9 }, weights: { complexity: 1 } },
    metrics: { complexity: 0.9, coupling: 0.4 },
  },
]
const details: Readonly<Record<string, FileDetail>> = {
  'src/main.py': {
    ...hotspots[0],
    findings: [{ path: 'src/main.py', rule_id: 'PY001', analyzer: 'ruff', severity: 'error', message: 'Fix this issue', start_line: 4, end_line: 4, remediation: 'Refactor safely.' }],
  },
}

describe('hotspots Markdown export', () => {
  it('exports filtered and sorted hotspot evidence with LLM instructions and related findings', () => {
    const file = createHotspotsMarkdownExport({
      repositoryUrl: 'https://github.com/acme/demo',
      analysisId: 'analysis-42',
      hotspots,
      totalHotspotsLoaded: 3,
      filters: { risks: ['critical'] },
      sort: { column: 'risk', direction: 'desc' },
      details,
      exportedAt: EXPORTED_AT,
    })

    expect(file.filename).toBe('demo-hotspots-2026-08-09-10-11-12.md')
    expect(file.content).toContain('# Hotspots for demo')
    expect(file.content).toContain('- Total hotspots loaded: 3')
    expect(file.content).toContain('- Risk filter: critical')
    expect(file.content).toContain('## Instructions for the coding model')
    expect(file.content).toContain('Do not invent evidence')
    expect(file.content).toContain('src/main.py')
    expect(file.content).toContain('Hotspot score: 0.91')
    expect(file.content).toContain('PY001')
    expect(file.content).toContain('Refactor safely.')
  })

  it('marks unavailable details without dropping the hotspot', () => {
    const file = createHotspotsMarkdownExport({
      repositoryUrl: 'https://github.com/acme/demo',
      analysisId: 'analysis-42',
      hotspots,
      details: {},
      exportedAt: EXPORTED_AT,
    })
    expect(file.content).toContain('Related findings: _Unavailable')
    expect(file.content).toContain('src/main.py')
  })

  it('escapes adversarial metadata, paths, messages, and remediation', () => {
    const unsafeHotspot: FileInsight = { ...hotspots[0], path: 'src/[unsafe]_*|.py', risk: { ...hotspots[0].risk!, version: 'v_[unsafe]*' } }
    const unsafeDetail: FileDetail = {
      ...unsafeHotspot,
      findings: [{ path: unsafeHotspot.path, rule_id: 'R|1', analyzer: 'tool', severity: 'high', category: 'type_[x]', title: 'Title_[x]*', message: 'Do *not* use `x` | now', evidence: 'Evidence_[x]*', start_line: 1, end_line: 1, remediation: 'Use [safe]_* instead.' }],
    }
    const file = createHotspotsMarkdownExport({
      repositoryUrl: 'https://github.com/acme/[demo]_*.git',
      analysisId: 'analysis_[unsafe]|1',
      hotspots: [unsafeHotspot],
      details: { [unsafeHotspot.path]: unsafeDetail },
      exportedAt: EXPORTED_AT,
    })
    expect(file.content).toContain('https://github.com/acme/\\[demo\\]\\_\\*.git')
    expect(file.content).toContain('analysis\\_\\[unsafe\\]\\|1')
    expect(file.content).toContain('src/\\[unsafe\\]\\_\\*\\|.py')
    expect(file.content).toContain('Risk version: v\\_\\[unsafe\\]\\*')
    expect(file.content).toContain('Title: Title\\_\\[x\\]\\*')
    expect(file.content).toContain('Type: type\\_\\[x\\]')
    expect(file.content).toContain('Do \\*not\\* use \\`x\\` \\| now')
    expect(file.content).toContain('Evidence: Evidence\\_\\[x\\]\\*')
    expect(file.content).toContain('Use \\[safe\\]\\_\\* instead.')
  })
})
