import { describe, expect, it } from 'vitest'
import {
  adoptable, batchIds, bigRequest, canRevert, categoriesOf, counts, defaultOpen, editContent, editText, filterItems, fmtTokens,
  jumpTarget, needsConfirm, pick, projectPath, query, refText, stepOf, type Suggestion,
  bodyText, checkScope, commandsOf, coverageMarks, diffScope, featureScope, impactScope, levelOf, peerLine, suspectOf, type Coverage,
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

describe('ai-suggest logic · M8-3 日常分析', () => {
  const ref = (id: string, label: string, type = 'device') => ({ id, label, type, found: true, device_id: 1 })

  it('正文、风险与优先级、更可能出错的一端', () => {
    const a = sg(1, { category: 'refs_exist', content: { text: 'x [[c1]]', risk: 'HIGH' } })
    expect(bodyText(a)).toBe('x [[c1]]')
    expect(levelOf(a)).toEqual({ k: 'risk', v: 'high', cls: 'hi' })
    const b = sg(2, { category: 'refs_exist', content: { text: 't', priority: 'low', suspect: 'd2' }, refs: [ref('d2', 'AGG-01')] })
    expect(levelOf(b)).toEqual({ k: 'prio', v: 'low', cls: 'lo' })
    expect(suspectOf(b)).toBe('AGG-01')
    expect(levelOf(sg(3, { content: { risk: 'extreme' } }))).toBeNull()
    expect(bodyText(sg(4, { category: 'script_valid', content: { script: 's', explain: 'why' } }))).toBe('why')
    expect(bodyText(sg(5))).toBe('')
  })

  it('推测对端与命令写法', () => {
    const p = sg(1, { category: 'peer_link', content: { a: 'd1', a_interface: 'GE0/1', b: 'd2' }, refs: [ref('d1', 'A'), ref('d2', 'B')] })
    expect(peerLine(p)).toEqual({ a: 'A GE0/1', b: 'B', external: false })
    const e = sg(2, { category: 'peer_link', content: { a: 'd1', b: 'u1', external: true, label: 'AS 65010' }, refs: [ref('d1', 'A')] })
    expect(peerLine(e)).toEqual({ a: 'A', b: 'AS 65010', external: true })
    expect(peerLine(sg(3))).toBeNull()
    const f = sg(4, { category: 'text_only', content: { text: 't', commands: [{ card: 'k1', text: 'mtu 9000' }, null] }, refs: [ref('k1', 'hw.mtu', 'card')] })
    expect(commandsOf(f)).toEqual([{ card: 'hw.mtu', text: 'mtu 9000' }])
  })

  it('差异、问题、命令卡的引用由页面处理，不换页', () => {
    expect(jumpTarget({ id: 'c1', type: 'diff', found: true, device_id: 3, node: 'interface[GE0/1]' })).toBeNull()
    expect(jumpTarget({ id: 'f1', type: 'finding', found: true, device_id: 3 })).toBeNull()
    expect(jumpTarget({ id: 'n1', type: 'interface', found: true, device_id: 3, node: 'x' })).not.toBeNull()
  })

  it('覆盖核对给差异表打标', () => {
    const cov: Coverage = { batch_id: 9, prefix: 'c', total: 3, covered: ['c1'], uncovered: [{ id: 'c2', label: 'L2', node: 'n2' }, { id: 'c3', label: 'L3' }], by_suggestion: {} }
    expect(coverageMarks([{ node: 'n1', label: 'L1' }, { node: 'n2' }, { label: 'L3' }], cov)).toEqual(['cov', 'uncov', 'uncov'])
    expect(coverageMarks([{ node: 'n1' }], null)).toEqual([''])
    expect(coverageMarks([{ node: 'n1' }], { ...cov, batch_id: null })).toEqual([''])
  })

  it('各页面的范围与后端一致', () => {
    expect(diffScope('compare', 3, 7)).toBe('compare:3:7')
    expect(checkScope(4)).toBe('check:4')
    expect(impactScope(2, 'up', ['b', 'a'])).toBe('impact:2:up:a,b')
    expect(impactScope(2, 'up', ['x'.repeat(300)]).length).toBe(200)
    expect(featureScope('interface.mtu', 'p1', 'p2')).toBe('feature:interface.mtu:p1:p2')
  })
})
