import { describe, expect, it } from 'vitest'
import {
  age, changedFields, isAi, nextId, offsetAfterRemoval, pageRange, parseTime, previewComplete, rejectNote,
  sortedKinds, sourceLine, splitTitle, totalCount, unknownCardEmpty, unknownCardReady,
} from './logic'

describe('审核队列逻辑', () => {
  it('类型按固定顺序排列，未知类型排后面，计数为 0 的不显示', () => {
    expect(sortedKinds({ conflict: 2, card: 5, zzz: 1, schema_node: 0 })).toEqual(['card', 'conflict', 'zzz'])
    expect(totalCount({ card: 5, conflict: 2 })).toBe(7)
    expect(totalCount({})).toBe(0)
  })

  it('标题拆成卡 ID 与语法', () => {
    expect(splitTitle('cisco-iosxe.mtu：mtu <bytes>')).toEqual({ id: 'cisco-iosxe.mtu', text: 'mtu <bytes>' })
    expect(splitTitle(' port-mode 1GE', 'x')).toEqual({ id: 'x', text: ' port-mode 1GE' })
  })

  it('来源与 AI 标记', () => {
    expect(isAi({ extracted_by: 'ai' })).toBe(true)
    expect(isAi({ rules: 'cisco-iosxe-md' })).toBe(false)
    expect(isAi(null)).toBe(false)
    expect(sourceLine({ title: 'address-family ipv4 (BGP)', version: '17.15' })).toBe('address-family ipv4 (BGP) · 17.15')
    expect(sourceLine({ file: 'a.md' })).toBe('a.md')
  })

  it('只提交改过的非空字段', () => {
    expect(changedFields({ syntax: 'mtu <n>', view: 'interface' }, { syntax: 'mtu <n>', view: 'interface' })).toBeNull()
    expect(changedFields({ syntax: 'mtu <n>' }, { syntax: ' mtu <bytes> ', view: '' })).toEqual({ syntax: 'mtu <bytes>' })
    expect(changedFields({}, { view: 'bgp', undo: 'no x' })).toEqual({ view: 'bgp', undo: 'no x' })
  })

  it('分页区间与删除后的偏移', () => {
    expect(pageRange(0, 50, 2350)).toEqual({ from: 1, to: 50, total: 2350 })
    expect(pageRange(2300, 50, 2350)).toEqual({ from: 2301, to: 2350, total: 2350 })
    expect(pageRange(0, 0, 0)).toEqual({ from: 0, to: 0, total: 0 })
    expect(offsetAfterRemoval(100, 0, 50)).toBe(50)
    expect(offsetAfterRemoval(100, 3, 50)).toBe(100)
    expect(offsetAfterRemoval(0, 0, 50)).toBe(0)
  })

  it('处理后选中下一项', () => {
    expect(nextId([1, 2, 3], 2)).toBe(3)
    expect(nextId([1, 2, 3], 3)).toBe(2)
    expect(nextId([1], 1)).toBeNull()
    expect(nextId([4, 5], 9)).toBe(4)
  })

  it('驳回备注', () => {
    expect(rejectNote('重复', '')).toBe('重复')
    expect(rejectNote('重复', ' 与 #3 相同 ')).toBe('重复：与 #3 相同')
  })

  it('时间按 UTC 解析并给出相对时间', () => {
    expect(parseTime('2026-10-18T00:46:28')?.toISOString()).toBe('2026-10-18T00:46:28.000Z')
    expect(parseTime('bad')).toBeNull()
    const now = new Date('2026-10-18T03:00:00Z')
    expect(age('2026-10-18T02:59:50', now)).toEqual([1, 'm'])
    expect(age('2026-10-18T00:30:00', now)).toEqual([2, 'h'])
    expect(age('2026-10-15T00:00:00+00:00', now)).toEqual([3, 'd'])
    expect(age(null, now)).toBeNull()
  })

  it('冲突预览是否完整', () => {
    expect(previewComplete('short')).toBe(true)
    expect(previewComplete('x'.repeat(4000))).toBe(false)
  })

  it('未识别行附卡的字段检查', () => {
    const c = { id: '', syntax: '', view: '', family: '', domain: '' }
    expect(unknownCardEmpty(c)).toBe(true)
    expect(unknownCardReady(c)).toBe(false)
    const full = { id: 'a', syntax: 'b', view: 'c', family: 'd', domain: 'e' }
    expect(unknownCardReady(full)).toBe(true)
    expect(unknownCardEmpty({ ...c, id: 'a' })).toBe(false)
  })
})
