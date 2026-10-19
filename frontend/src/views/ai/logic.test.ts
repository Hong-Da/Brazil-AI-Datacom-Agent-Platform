import { describe, expect, it } from 'vitest'
import {
  autoTarget, buildPayload, choiceValue, chosenClosed, distinct, emptyForm, filterCalls, fmtTokens, formFrom, monthStart,
  normReason, parseChoice, payloadIsEmpty, reasonTarget, reasonTone, taskModels, usageByTask, validateConn,
  type AiCall, type ConnOption,
} from './logic'

describe('接口表单', () => {
  it('从接口生成表单，未知类型回到默认', () => {
    const f = formFrom({ name: 'lab', provider: 'local', base_url: 'http://x/v1', model: 'q', public: true })
    expect(f).toMatchObject({ name: 'lab', provider: 'local', base_url: 'http://x/v1', model: 'q', public: true, enabled: true, model_ask: '' })
    expect(formFrom({ provider: 'bogus' as never }).provider).toBe('openai')
  })
  it('校验：名称、地址、模型、Anthropic 的 Key', () => {
    const f = { ...emptyForm(), provider: 'anthropic' as const }
    expect(validateConn(f, false, '', false)).toEqual({ name: 'errName', model: 'errModel', api_key: 'errKey' })
    expect(validateConn({ ...f, name: 'a', model: 'm' }, true, '', false)).toEqual({})
    expect(validateConn({ ...f, name: 'a', model: 'm' }, true, '', true)).toEqual({ api_key: 'errKey' })
    const o = { ...emptyForm(), name: 'x', model: 'm' }
    expect(validateConn(o, false, '', false)).toEqual({ base_url: 'errBaseUrl' })
    expect(validateConn({ ...o, base_url: 'ftp://x' }, false, '', false)).toEqual({ base_url: 'errUrl' })
    expect(validateConn({ ...o, name: '', base_url: 'http://x' }, false, '', false, false)).toEqual({})
    expect(validateConn({ ...o, name: 'n'.repeat(65), base_url: 'http://x' }, false, '', false)).toEqual({ name: 'errName' })
  })
})

describe('保存内容', () => {
  it('新建时提交全部，修改时只提交改动', () => {
    const f = { ...emptyForm(), name: ' lab ', base_url: 'http://x/v1', model: 'q' }
    const p = buildPayload(null, f, 'sk-1', false, false)
    expect(p).toMatchObject({ name: 'lab', provider: 'openai', model: 'q', public: false, enabled: true, api_key: 'sk-1' })
    const orig = formFrom({ name: 'lab', provider: 'openai', base_url: 'http://x/v1', model: 'q' })
    expect(payloadIsEmpty(buildPayload(orig, { ...orig }, '', false, true))).toBe(true)
    expect(buildPayload(orig, { ...orig, public: true, model_ask: 'big' }, '', false, true)).toEqual({ public: true, model_ask: 'big' })
    expect(buildPayload(orig, { ...orig }, '', true, true)).toEqual({ clear_api_key: true })
    expect(buildPayload(orig, { ...orig }, '', true, false)).toEqual({})
  })
  it('个人接口不提交名称与开关', () => {
    const p = buildPayload(null, { ...emptyForm(), name: 'x', base_url: 'http://y', model: 'm' }, '', false, false, false, false)
    expect(p).not.toHaveProperty('name')
    expect(p).not.toHaveProperty('public')
    expect(p).toMatchObject({ provider: 'openai', base_url: 'http://y', model: 'm' })
  })
  it('列出填写了专门模型的用途', () => {
    expect(taskModels({ model: 'm', model_extract: 'cheap', model_merge: '', model_ask: ' ', model_generate: 'big' })).toEqual([['extract', 'cheap'], ['generate', 'big']])
  })
})

describe('我的 AI', () => {
  const opts: ConnOption[] = [
    { id: 1, name: 'default', provider: 'anthropic', model: 'c', public: false },
    { id: 2, name: 'lab', provider: 'local', model: 'q', public: true },
  ]
  it('单选框的值与解析', () => {
    expect(choiceValue('connection', 2)).toBe('c:2')
    expect(choiceValue('personal', null)).toBe('personal')
    expect(parseChoice('c:2')).toEqual({ choice: 'connection', connection_id: 2 })
    expect(parseChoice('none')).toEqual({ choice: 'none', connection_id: null })
    expect(parseChoice('weird')).toEqual({ choice: 'auto', connection_id: null })
  })
  it('所选接口不在可选列表里即为已关闭', () => {
    expect(chosenClosed({ choice: 'connection', connection_id: 3, options: opts })).toBe(true)
    expect(chosenClosed({ choice: 'connection', connection_id: 2, options: opts })).toBe(false)
    expect(chosenClosed({ choice: 'auto', connection_id: null, options: [] })).toBe(false)
  })
  it('自动选择：管理员第一个可选，普通用户第一个公开', () => {
    expect(autoTarget({ options: opts, is_admin: true })?.id).toBe(1)
    expect(autoTarget({ options: opts, is_admin: false })?.id).toBe(2)
    expect(autoTarget({ options: [], is_admin: false })).toBeNull()
  })
  it('原因的去处与样式', () => {
    expect(reasonTarget('no_connection', true)).toBe('ai-settings')
    expect(reasonTarget('no_connection', false)).toBe('my-ai')
    expect(reasonTarget('public_closed', true)).toBe('my-ai')
    expect(reasonTone('public_closed')).toBe('warn')
    expect(reasonTone('disabled_by_user')).toBe('plain')
    expect(normReason('no_public')).toBe('no_public')
    expect(normReason('x')).toBeNull()
    expect(normReason(undefined)).toBeNull()
  })
})

describe('调用记录', () => {
  const calls: AiCall[] = [
    { id: 1, task: 'extract', provider: 'openai', model: 'm', tokens_in: 100, tokens_out: 20, status: 'ok', error: null, review_item_id: null, created_at: '2026-10-02T00:00:00+00:00', user: 'alice', connection: 'default' },
    { id: 2, task: 'extract', provider: 'openai', model: 'm', tokens_in: 50, tokens_out: 0, status: 'error', error: 'x', review_item_id: null, created_at: '2026-10-03T00:00:00+00:00', user: 'bob', connection: 'personal' },
    { id: 3, task: 'test', provider: 'openai', model: 'm', tokens_in: 5, tokens_out: 1, status: 'ok', error: null, review_item_id: null, created_at: '2026-09-01T00:00:00+00:00', user: 'alice', connection: 'default' },
  ]
  it('按用户、接口、任务筛选', () => {
    expect(filterCalls(calls, { user: 'alice' }).map((c) => c.id)).toEqual([1, 3])
    expect(filterCalls(calls, { connection: 'personal' }).map((c) => c.id)).toEqual([2])
    expect(filterCalls(calls, { user: 'alice', task: 'test' }).map((c) => c.id)).toEqual([3])
    expect(distinct(calls, 'user')).toEqual(['alice', 'bob'])
    expect(distinct(calls, 'task')).toEqual(['extract', 'test'])
  })
  it('按任务汇总，可只算本月', () => {
    const all = usageByTask(calls)
    expect(all[0]).toMatchObject({ task: 'extract', calls: 2, errors: 1, tokensIn: 150 })
    expect(usageByTask(calls, monthStart(new Date(2026, 9, 15))).map((u) => u.task)).toEqual(['extract'])
  })
  it('token 数格式化', () => {
    expect(fmtTokens(1234)).toBe('1,234')
    expect(fmtTokens(12345)).toBe('12.3k')
    expect(fmtTokens(1_500_000)).toBe('1.50M')
  })
})
