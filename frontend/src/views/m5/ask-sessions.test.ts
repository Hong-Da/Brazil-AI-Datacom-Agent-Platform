import { describe, expect, it } from 'vitest'
import { attachDetail, currentOf, dayGroup, shortWhen, type Attachment, type SessionTurn } from './ask-sessions'

const now = new Date(2026, 9, 21, 15, 0)
const t = (k: string, p?: Record<string, unknown>) => `${k}${p ? JSON.stringify(p) : ''}`

describe('AI 查询会话（REQ-052～054）', () => {
  it('按最近更新分组', () => {
    expect(dayGroup(new Date(2026, 9, 21, 9, 5).toISOString(), now)).toBe('today')
    expect(dayGroup(new Date(2026, 9, 18).toISOString(), now)).toBe('week')
    expect(dayGroup(new Date(2026, 8, 30).toISOString(), now)).toBe('earlier')
    expect(dayGroup(null, now)).toBe('earlier')
  })
  it('列表时间：今天显示时分，否则月日', () => {
    expect(shortWhen(new Date(2026, 9, 21, 9, 5).toISOString(), now)).toBe('09:05')
    expect(shortWhen(new Date(2026, 9, 19, 9, 5).toISOString(), now)).toBe('10-19')
  })
  it('附件说明', () => {
    const cfg: Attachment = { id: 1, name: 'a.cfg', kind: 'config', size: 1, meta: { vendor: 'huawei', device: 'EDGE-1' } }
    expect(attachDetail(cfg, t)).toBe('Huawei · EDGE-1')
    const xl: Attachment = { id: 2, name: 'p.xlsx', kind: 'doc', size: 1, meta: { format: 'xlsx', sheets: 2, rows: 120, chars: 4812 } }
    expect(attachDetail(xl, t)).toBe(`ask.att.sheets{"n":2,"rows":120} · ask.att.chars{"n":"${(4812).toLocaleString()}"}`)
    const img: Attachment = { id: 3, name: 't.png', kind: 'image', size: 1, meta: {} }
    expect(attachDetail(img, t)).toBe('ask.att.notSanitized')
  })
  it('当前版本', () => {
    const turn = { id: 1, position: 1, current: 1, versions: [{ question: 'a' }, { question: 'b' }] } as unknown as SessionTurn
    expect(currentOf(turn).question).toBe('b')
  })
})
