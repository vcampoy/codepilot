const MODELS_BY_PROVIDER: Readonly<Record<string, readonly string[]>> = {
  openai: ['gpt-4o-mini', 'gpt-4o'],
}

export function getLlmModelOptions(provider: string, persistedModel: string | null): string[] {
  const normalizedProvider = provider.trim().toLowerCase()
  const catalog = MODELS_BY_PROVIDER[normalizedProvider]
  if (!catalog) return []
  if (!persistedModel || catalog.includes(persistedModel)) return [...catalog]
  return [persistedModel, ...catalog]
}
