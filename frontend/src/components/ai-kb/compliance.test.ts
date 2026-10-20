import { describe, expect, it } from 'vitest'
import type { Suggestion } from '@/components/ai-suggest/logic'
import { reportScope } from '@/components/ai-suggest/logic'
import { clauseStates, reviewRows, splitClauses, stepClasses, waiverScope, waiverTexts } from './compliance'

function sug(p: Partial<Suggestion>): Suggestion {
  return {
    id: 1, batch_id: 1, skill: 'rule-draft', category: 'kb_review', kind: '', title: 't', content: null, original: null, edited: false,
    refs: [], check: {}, check_status: 'pass', status: 'pending', kb: true, connection: '', created_by: '', created_at: null,
    decided_by: '', decided_at: null, adopt_info: null, note: '', reverted_by: '', reverted_at: null, device_id: null, scope_key: 'rules:standard',
    ...p,
  }
}

describe('splitClauses（与后端 split_clauses 一致）', () => {
  it('编号行开始新条款，续行并入上一条', () => {
    const c = splitClauses('§4.2.1 上联接口必须配置描述\n格式为 UL-to-<对端>\n5.1 SNMP 团体名不得为 public\n第三条 管理口绑定 ACL')
    expect(c.map((x) => [x.id, x.no])).toEqual([['s1', '4.2.1'], ['s2', '5.1'], ['s3', '第三条']])
    expect(c[0].text).toBe('§4.2.1 上联接口必须配置描述 格式为 UL-to-<对端>')
  })
  it('没有编号时按空行分段，编号为 ¶n；标题的 # 去掉', () => {
    const c = splitClauses('# 总则\n\n所有设备开启 NTP\n同步到两台服务器\n\nBGP 必须认证')
    expect(c.map((x) => x.no)).toEqual(['¶1', '¶2', '¶3'])
    expect(c[0].text).toBe('总则')
    expect(c[1].text).toBe('所有设备开启 NTP 同步到两台服务器')
  })
  it('一句话描述排在最后，编号 *', () => {
    expect(splitClauses('', '管理口必须绑定 ACL 2000')).toEqual([{ id: 's1', no: '*', text: '管理口必须绑定 ACL 2000' }])
    expect(splitClauses('SEC-12 a', 'b').map((x) => x.no)).toEqual(['SEC-12', '*'])
  })
  it('最多 80 条', () => {
    const t = Array.from({ length: 90 }, (_, i) => `${i + 1}. x`).join('\n')
    expect(splitClauses(t)).toHaveLength(80)
  })
})

describe('clauseStates', () => {
  const ref = (id: string) => ({ id, found: true, label: id })
  it('只看指定批次；已送审 > 有草稿 > 未通过', () => {
    const items = [
      sug({ id: 1, refs: [ref('s1')], status: 'adopted' }),
      sug({ id: 2, refs: [ref('s1'), ref('s2')], check_status: 'warn' }),
      sug({ id: 3, refs: [ref('s3')], check_status: 'reject' }),
      sug({ id: 4, refs: [ref('s4')], status: 'dismissed' }),
      sug({ id: 5, batch_id: 2, refs: [ref('s5')] }),
      sug({ id: 6, refs: [{ id: 'n1', found: true }] }),
    ]
    expect(clauseStates(items, 1)).toEqual({ s1: 'sent', s2: 'draft', s3: 'failed' })
    expect(clauseStates(items, null)).toEqual({})
  })
})

describe('stepClasses', () => {
  it('四步', () => {
    expect(stepClasses(false, false, false, false)).toEqual(['cur', '', '', ''])
    expect(stepClasses(true, false, false, false)).toEqual(['done', 'cur', '', ''])
    expect(stepClasses(true, true, true, false)).toEqual(['done', 'cur', '', ''])
    expect(stepClasses(true, false, true, false)).toEqual(['done', 'done', 'cur', ''])
    expect(stepClasses(true, false, true, true)).toEqual(['done', 'done', 'done', 'cur'])
  })
})

describe('reviewRows', () => {
  it('只列有审核条目的采纳记录，状态取自 /review', () => {
    const items = [
      sug({ id: 1, status: 'adopted', adopt_info: { review_item_id: 7 }, check: { title_display: 'SEC-BGP-AUTH' } }),
      sug({ id: 2, status: 'adopted', adopt_info: { review_item_id: 8 } }),
      sug({ id: 3, status: 'reverted', adopt_info: { review_item_id: 9 } }),
      sug({ id: 4, status: 'adopted', adopt_info: null }),
    ]
    expect(reviewRows(items, { 7: 'approved' })).toEqual([
      { sid: 1, reviewId: 7, title: 'SEC-BGP-AUTH', status: 'approved' },
      { sid: 2, reviewId: 8, title: 't', status: 'pending' },
    ])
  })
})

describe('waiverTexts', () => {
  it('已采纳的优先，否则最新的；拒绝与忽略的不用；优先用代码填好的 display', () => {
    const items = [
      sug({ id: 1, category: 'text_only', kind: 'reason', content: { text: '旧理由' } }),
      sug({ id: 2, category: 'text_only', kind: 'reason', content: { text: '新理由' } }),
      sug({ id: 3, category: 'text_only', kind: 'compensating', content: { text: 'x' }, check: { display: '补偿 ac01' }, status: 'adopted' }),
      sug({ id: 4, category: 'text_only', kind: 'compensating', content: { text: '更新的' } }),
      sug({ id: 5, category: 'text_only', kind: 'reason', content: { text: '编造' }, check_status: 'reject' }),
    ]
    expect(waiverTexts(items)).toEqual({ reason: '新理由', compensating: '补偿 ac01' })
    expect(waiverTexts([])).toEqual({ reason: '', compensating: '' })
  })
  it('范围', () => {
    expect(waiverScope(3, 'strict', 'BL-SSH-01')).toBe('waiver:3:strict:BL-SSH-01')
  })
})

describe('报告摘要的范围（共用 reportScope）', () => {
  it('配置文本时为 null', () => {
    expect(reportScope('check', { device_id: null })).toBeNull()
    expect(reportScope('change', { current: { device_id: 1 }, target: {} })).toBeNull()
    expect(reportScope('compare', { a: { device_id: 1, version_id: 5 }, b: { device_id: 2 } })).toBe('report:compare:v5:d2')
  })
})
