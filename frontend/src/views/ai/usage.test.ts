import { describe, expect, it } from 'vitest'
import { csvName, dayBars, labelIdx, lastDays, niceMax, shareOf, shortDay, usageQuery, validRange, type UsageRow } from './usage'

const row = (key: string, i: number, o: number): UsageRow => ({ key, calls: 1, errors: 0, tokens_in: i, tokens_out: o })

describe('用量：时间范围与参数', () => {
  it('最近 n 天含今天（UTC）', () => {
    expect(lastDays(7, new Date('2026-10-19T23:30:00Z'))).toEqual({ from: '2026-10-13', to: '2026-10-19' })
    expect(lastDays(1, new Date('2026-03-01T00:10:00Z'))).toEqual({ from: '2026-03-01', to: '2026-03-01' })
  })
  it('范围校验与查询字符串', () => {
    expect(validRange('2026-10-01', '2026-10-19')).toBe(true)
    expect(validRange('2026-10-20', '2026-10-19')).toBe(false)
    expect(validRange('2026-1-1', '2026-10-19')).toBe(false)
    expect(usageQuery({ from: 'a', to: 'b' })).toBe('from=a&to=b')
    expect(usageQuery({ from: 'a', to: 'b', group: 'user', user: 'alice', connectionId: 3 })).toBe('from=a&to=b&group=user&user=alice&connection_id=3')
    expect(csvName('model', '2026-10-01', '2026-10-19')).toBe('ai-usage-model-2026-10-01-2026-10-19.csv')
  })
})

describe('用量：图表几何', () => {
  it('坐标轴上限取 1/2/5×10^k', () => {
    expect(niceMax(0)).toBe(1)
    expect(niceMax(7)).toBe(10)
    expect(niceMax(130)).toBe(200)
    expect(niceMax(4100)).toBe(5000)
    expect(niceMax(1000)).toBe(1000)
  })
  it('堆叠柱按上限折算高度，柱间留缝', () => {
    const { bars, max } = dayBars([row('d1', 60, 20), row('d2', 0, 0), row('d3', 30, 10)], 300, 100)
    expect(max).toBe(100)
    expect(bars).toHaveLength(3)
    expect(bars[0]).toMatchObject({ x: 1, w: 98, hIn: 60, hOut: 20 })
    expect(bars[1].hIn + bars[1].hOut).toBe(0)
    expect(bars[2].x).toBe(201)
  })
  it('日期标签均匀抽取、包含首尾', () => {
    expect(labelIdx(5)).toEqual([0, 1, 2, 3, 4])
    const idx = labelIdx(30)
    expect(idx[0]).toBe(0)
    expect(idx[idx.length - 1]).toBe(29)
    expect(idx.length).toBeLessThanOrEqual(8)
    expect(labelIdx(0)).toEqual([])
    expect(shortDay('2026-10-19')).toBe('10-19')
  })
  it('占比相对第一名', () => {
    expect(shareOf([row('a', 80, 20), row('b', 40, 10)])).toEqual([1, 0.5])
    expect(shareOf([])).toEqual([])
  })
})
