export type FailedAnalysisDeletion = {
  id: string
  error: unknown
}

export type AnalysisDeletionResult = {
  deleted: string[]
  failed: FailedAnalysisDeletion[]
}

export async function deleteAnalyses(ids: readonly string[], deleteAnalysis: (id: string) => Promise<void>): Promise<AnalysisDeletionResult> {
  const results = await Promise.allSettled(ids.map((id) => deleteAnalysis(id)))
  return results.reduce<AnalysisDeletionResult>((result, outcome, index) => {
    const id = ids[index]
    if (outcome.status === 'fulfilled') result.deleted.push(id)
    else result.failed.push({ id, error: outcome.reason })
    return result
  }, { deleted: [], failed: [] })
}
