import { describe, expect, it } from 'vitest'
import {
  buildPayload, effectiveModel, envName, fmtTokens, formFrom, isEnv, monthStart, payloadIsEmpty, usageByTask, validateAi,
  type AiCall, type AiSettings,
} from './logic'

const settings = (o: Partial<AiSettings> = {}): AiSettings => ({
  provider: '', base_url: '', model: '', model_extract: '', model_merge: '', timeout: 60, max_tokens: 4096, api_key_set: false,
  sources: { provider: 'file', base_url: 'file', model: 'file', model_extract: 'file', model_merge: 'file', timeout: 'file', max_tokens: 'file', api_key: 'file' },
  ...o,
})

describe('AI 表单', () => {
  it('从设置生成表单', () => {
    expect(formFrom(settings({ provider: 'openai', timeout: 30 }))).toMatchObject({ provider: 'openai', timeout: 30, max_tokens: 4096 })
  })
  it('校验：不使用 AI 时不检查', () => {
    expect(validateAi(formFrom(settings({ timeout: 1 })), false, '', false)).toEqual({})
  })
  it('校验：各接口类型的必填项与范围', () => {
    const f = { ...formFrom(settings()), provider: 'openai' as const }
    expect(validateAi(f, false, '', false)).toEqual({ base_url: 'errBaseUrl', model: 'errModel' })
    expect(validateAi({ ...f, base_url: 'ftp://x', model: 'm' }, false, '', false)).toEqual({ base_url: 'errUrl' })
    const a = { ...f, provider: 'anthropic' as const, model: 'claude', timeout: 3, max_tokens: 100 }
    expect(validateAi(a, false, '', false)).toEqual({ api_key: 'errKey', timeout: 'errRange', max_tokens: 'errRange' })
    expect(validateAi({ ...a, timeout: 60, max_tokens: 4096 }, true, '', false)).toEqual({})
    expect(validateAi({ ...a, timeout: 60, max_tokens: 4096 }, true, '', true)).toEqual({ api_key: 'errKey' })
    expect(validateAi({ ...f, provider: 'local', base_url: 'http://127.0.0.1:11434/v1', model: 'q' }, false, '', false)).toEqual({})
  })
})

describe('保存内容', () => {
  it('只提交改动的项，API Key 有输入才提交', () => {
    const s = settings({ provider: 'openai', base_url: 'http://a/v1', model: 'm', api_key_set: true })
    const f = { ...formFrom(s), model: ' m2 ' }
    expect(buildPayload(s, f, '', false)).toEqual({ model: 'm2', clear_api_key: false })
    expect(buildPayload(s, formFrom(s), ' sk-1 ', true)).toEqual({ api_key: 'sk-1', clear_api_key: false })
    expect(buildPayload(s, formFrom(s), '', true)).toEqual({ clear_api_key: true })
    expect(payloadIsEmpty(buildPayload(s, formFrom(s), '', false))).toBe(true)
    expect(payloadIsEmpty({ clear_api_key: true })).toBe(false)
  })
  it('环境变量来源的项不提交', () => {
    const s = settings({ sources: { ...settings().sources, provider: 'env', api_key: 'env' } })
    const f = { ...formFrom(s), provider: 'local' as const, model: 'x' }
    expect(buildPayload(s, f, 'k', true)).toEqual({ model: 'x', clear_api_key: false })
    expect(isEnv(s.sources, 'provider')).toBe(true)
    expect(isEnv(s.sources, 'model')).toBe(false)
    expect(envName('base_url')).toBe('LMESH_AI__BASE_URL')
  })
  it('任务模型留空时用默认模型', () => {
    const f = { ...formFrom(settings()), model: 'big', model_extract: 'small' }
    expect(effectiveModel(f, 'extract')).toBe('small')
    expect(effectiveModel(f, 'merge')).toBe('big')
  })
})

describe('调用记录', () => {
  const call = (o: Partial<AiCall>): AiCall => ({
    id: 1, task: 'extract', provider: 'openai', model: 'm', tokens_in: 100, tokens_out: 10, status: 'ok', error: null, review_item_id: null,
    created_at: '2026-10-10T08:00:00', ...o,
  })
  it('按任务汇总，可只算本月', () => {
    const calls = [call({}), call({ status: 'error', tokens_in: null, tokens_out: null }), call({ task: 'test', tokens_in: 5, tokens_out: 1 }), call({ created_at: '2026-09-30T08:00:00' })]
    const u = usageByTask(calls, monthStart(new Date(2026, 9, 17)))
    expect(u).toEqual([
      { task: 'extract', calls: 2, ok: 1, errors: 1, tokensIn: 100, tokensOut: 10 },
      { task: 'test', calls: 1, ok: 1, errors: 0, tokensIn: 5, tokensOut: 1 },
    ])
    expect(usageByTask(calls)[0].calls).toBe(3)
  })
  it('token 数格式化', () => {
    expect(fmtTokens(950)).toBe('950')
    expect(fmtTokens(12_345)).toBe('12.3k')
    expect(fmtTokens(1_940_000)).toBe('1.94M')
  })
})
