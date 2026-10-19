import { describe, expect, it } from 'vitest'
import {
  adoptable, batchIds, bigRequest, canRevert, categoriesOf, counts, defaultOpen, editContent, editText, filterItems, fmtTokens,
  jumpTarget, needsConfirm, pick, projectPath, query, refText, stepOf, type Suggestion,
} from './logic'

function sg(id: number, extra: Partial<Suggestion> = {}): Suggestion {
  return {
    id, batch_id: 1, skill: 'topology-roles', category: 'view_hint', kind: 'role', title: `t${id}`, content: {}, original: null,
    edited: false, refs: [], check: {}, check_status: 'pass', status: 'pending', kb: false, connection: 'default',
    created_by: 'alice', created_at: null, decided_by: '', decided_at: null, adopt_info: null, note: '', reverted_by: '',
    reverted_at: null, device_id: null, scope_key: 'topology', ...extra,
  }
}

describe('ai-suggest logic', () => {
  const items = [
    sg(1),
    sg(2, { check_status: 'warn' }),
    sg(3, { check_status: 'reject' }),
    sg(4, { category: 'script_valid' }),
    sg(5, { status: 'adopted' }),
    sg(6, { status: 'dismissed' }),
  ]

  it('批量采纳只取校验通过且待处理的，可按类别', () => {
    expect(batchIds(items)).toEqual([1, 4])
    expect(batchIds(items, 'view_hint')).toEqual([1])
    expect(categoriesOf(items)).toEqual(['view_hint', 'script_valid'])
  })

  it('计数、可否采纳、默认展开（通过的折叠，有警告或被拒绝的展开）', () => {
    const c = counts(items)
    expect([c.pass, c.warn, c.reject, c.pending, c.adopted, c.dismissed]).toEqual([4, 1, 1, 4, 1, 1])
    expect(adoptable(items[2])).toBe(false)
    expect(adoptable(items[5])).toBe(true)
    expect(adoptable(items[4])).toBe(false)
    expect(items.map(defaultOpen)).toEqual([false, true, true, false, false, false])
  })

  it('筛选：待处理含已撤销的', () => {
    expect(filterItems([...items, sg(7, { status: 'reverted' })], 'pending').map((x) => x.id)).toEqual([1, 2, 3, 4, 7])
    expect(filterItems(items, 'adopted').map((x) => x.id)).toEqual([5])
    expect(filterItems(items, 'all')).toHaveLength(6)
  })

  it('运行四步与 token', () => {
    expect(stepOf('sanitize', 'running')).toBe(0)
    expect(stepOf('generate', 'running')).toBe(2)
    expect(stepOf('check', 'running')).toBe(3)
    expect(stepOf('', 'queued')).toBe(0)
    expect(stepOf('check', 'done')).toBe(4)
    expect(fmtTokens(186000)).toBe('186.0k')
    expect(fmtTokens(320)).toBe('320')
    expect(bigRequest(60000, 50000)).toBe(true)
    expect(bigRequest(60000, 0)).toBe(false) // 0 = 不提示（全局 ai.warn_tokens 或个人关闭）
  })

  it('只有会改配置、脚本或知识库的采纳需要二次确认', () => {
    expect(needsConfirm('script_valid')).toBe(true)
    expect(needsConfirm('kb_review')).toBe(true)
    expect(needsConfirm('view_hint')).toBe(false)
    expect(needsConfirm('text_only')).toBe(false)
  })

  it('30 天内可撤销', () => {
    const now = new Date('2026-10-30T00:00:00Z')
    expect(canRevert(sg(1, { status: 'adopted', decided_at: '2026-10-20T00:00:00Z' }), now)).toBe(true)
    expect(canRevert(sg(1, { status: 'adopted', decided_at: '2026-09-01T00:00:00Z' }), now)).toBe(false)
    expect(canRevert(sg(1, { status: 'pending', decided_at: '2026-10-29T00:00:00Z' }), now)).toBe(false)
  })

  it('引用跳转：对象到配置图（带节点），设备到设备分析，不存在的不跳', () => {
    expect(jumpTarget({ id: 'n1', found: true, node: 'interface[G0/1]', device_id: 3 })).toEqual({ name: 'device-graph', params: { id: 3 }, query: { node: 'interface[G0/1]' } })
    expect(jumpTarget({ id: 'd1', found: true, type: 'device', device_id: 3 })).toEqual({ name: 'device-analysis', params: { id: 3 } })
    expect(jumpTarget({ found: true, line: 12, device_id: 3 })).toEqual({ name: 'device-graph', params: { id: 3 }, query: { line: '12' } })
    expect(jumpTarget({ id: 'd9', found: false })).toBeNull()
    expect(refText({ found: true, line: 12 })).toBe('L12')
    expect(refText({ id: 'n1', found: true, label: 'Gi0/1' })).toBe('Gi0/1')
  })

  it('编辑：文字类改正文，其他类改 JSON，不合法返回 null', () => {
    const txt = sg(1, { category: 'text_only', content: { text: 'a' } })
    expect(editText(txt)).toBe('a')
    expect(editContent(txt, 'b')).toEqual({ text: 'b' })
    const hint = sg(2, { content: { target: 'd1', key: 'role', value: 'pe' } })
    expect(JSON.parse(editText(hint))).toEqual({ target: 'd1', key: 'role', value: 'pe' })
    expect(editContent(hint, '{"value":"p"}')).toEqual({ value: 'p' })
    expect(editContent(hint, '[1]')).toBeNull()
    expect(editContent(hint, 'nope')).toBeNull()
    expect(editContent(sg(3, { category: 'script_valid', content: { device: 'd1', script: 'x' } }), 'y')).toEqual({ device: 'd1', script: 'y' })
  })

  it('路径与文案', () => {
    expect(projectPath('alice/lab', '/ai/suggestions')).toBe('/projects/alice%2Flab/ai/suggestions')
    expect(query({ skill: 'x', scope: 'device:3', none: null, e: '' })).toBe('?skill=x&scope=device%3A3')
    expect(query({})).toBe('')
    expect(pick({ 'zh-CN': '中', en: 'en' }, 'pt-BR')).toBe('en')
    expect(pick(undefined, 'en')).toBe('')
  })
})
