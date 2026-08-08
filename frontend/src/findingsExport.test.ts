import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AnalysisFinding } from './api'
import {
  createFindingsMarkdownExport,
  downloadMarkdownFile,
  repositoryNameFromUrl,
} from './findingsExport'

const FINDINGS: readonly AnalysisFinding[] = Object.freeze([
  {
    path: 'src/main.py',
    rule_id: 'E501',
    analyzer: 'python.ruff',
    severity: 'warning',
    message: 'Line contains | and <unsafe>\nsecond line',
    start_line: 12,
    end_line: 14,
  },
  {
    path: 'src/app.ts',
    rule_id: 'no-any',
    analyzer: 'javascript.eslint',
    severity: 'error',
    message: 'Avoid any',
    start_line: 3,
    end_line: 3,
  },
])

const EXPORTED_AT = new Date(2026, 7, 8, 9, 4, 5)

afterEach(() => {
  vi.restoreAllMocks()
})

describe('findings Markdown export', () => {
  it('extracts and sanitizes the repository name from Git URLs', () => {
    expect(repositoryNameFromUrl('https://github.com/vcampoy/codepilot/')).toBe('codepilot')
    expect(repositoryNameFromUrl('https://github.com/vcampoy/codepilot.git')).toBe('codepilot')
    expect(repositoryNameFromUrl('not a URL')).toBe('repository')
  })

  it('creates a timestamped filename and Markdown containing every finding', () => {
    const exported = createFindingsMarkdownExport({
      repositoryUrl: 'https://github.com/vcampoy/codepilot',
      analysisId: 'analysis-123',
      findings: FINDINGS,
      exportedAt: EXPORTED_AT,
    })

    expect(exported.filename).toBe('codepilot-findings-2026-08-08-09-04-05.md')
    expect(exported.content).toContain('# Findings for codepilot')
    expect(exported.content).toContain('- Repository: https://github.com/vcampoy/codepilot')
    expect(exported.content).toContain('- Analysis: analysis-123')
    expect(exported.content).toContain('- Total findings: 2')
    expect(exported.content).toContain('warning | E501 | src/main.py:12-14 | python.ruff | Line contains \\| and &lt;unsafe&gt;<br>second line')
    expect(exported.content).toContain('error | no-any | src/app.ts:3 | javascript.eslint | Avoid any')
  })

  it('downloads the Markdown and releases browser resources', () => {
    const anchor = {
      href: '',
      download: '',
      click: vi.fn(),
    } as unknown as HTMLAnchorElement
    const documentRef = {
      createElement: vi.fn(() => anchor),
      body: {
        appendChild: vi.fn(),
        removeChild: vi.fn(),
      },
    } as unknown as Document
    const urlApi = {
      createObjectURL: vi.fn(() => 'blob:findings'),
      revokeObjectURL: vi.fn(),
    }
    const file = { filename: 'codepilot-findings.md', content: '# Findings' }

    downloadMarkdownFile(file, documentRef, urlApi)

    expect(urlApi.createObjectURL).toHaveBeenCalledWith(expect.any(Blob))
    expect(anchor.href).toBe('blob:findings')
    expect(anchor.download).toBe('codepilot-findings.md')
    expect(anchor.click).toHaveBeenCalledOnce()
    expect(documentRef.body.appendChild).toHaveBeenCalledWith(anchor)
    expect(documentRef.body.removeChild).toHaveBeenCalledWith(anchor)
    expect(urlApi.revokeObjectURL).toHaveBeenCalledWith('blob:findings')
  })
})
