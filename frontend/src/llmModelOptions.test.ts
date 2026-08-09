import { describe, expect, it } from 'vitest'
import { getLlmModelOptions } from './llmModelOptions'

describe('LLM model options', () => {
  it('returns the supported OpenAI models', () => {
    expect(getLlmModelOptions('openai', 'gpt-4o-mini')).toEqual(['gpt-4o-mini', 'gpt-4o'])
    expect(getLlmModelOptions(' OpenAI ', 'gpt-4o-mini')).toEqual(['gpt-4o-mini', 'gpt-4o'])
  })

  it('preserves a persisted model that is not in the current catalog', () => {
    expect(getLlmModelOptions('openai', 'future-model')).toEqual(['future-model', 'gpt-4o-mini', 'gpt-4o'])
  })

  it('returns no options for an unknown provider', () => {
    expect(getLlmModelOptions('unknown', 'custom-model')).toEqual([])
  })
})
