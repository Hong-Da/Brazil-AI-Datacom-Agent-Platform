import { describe, expect, it } from 'vitest'
import { canEdit, copyId, initialTab, splitByTab, tabOf, validAssetId } from './scope'

describe('模板与规则集的归属', () => {
  const rows = [
    { id: 'a', scope: 'shared' as const, editable: false },
    { id: 'b', scope: 'mine' as const, editable: true },
    { id: 'c', scope: 'user' as const, owner: 'liwei', editable: true },
    { id: 'd', scope: 'builtin' as const, editable: false },
    { id: 'e' },
  ]
  it('页签：我的 = mine、user；其余（含没有归属信息的）为共享', () => {
    expect(rows.map(tabOf)).toEqual(['shared', 'mine', 'mine', 'shared', 'shared'])
    const g = splitByTab(rows)
    expect(g.mine.map((x) => x.id)).toEqual(['b', 'c'])
    expect(g.shared.map((x) => x.id)).toEqual(['a', 'd', 'e'])
  })
  it('可编辑：没有 editable 字段时按可编辑', () => {
    expect(canEdit(rows[0])).toBe(false)
    expect(canEdit(rows[4])).toBe(true)
    expect(canEdit(null)).toBe(false)
  })
  it('初始页签跟着选中的条目，否则有我的就看我的', () => {
    expect(initialTab(rows, 'a')).toBe('shared')
    expect(initialTab(rows, 'c')).toBe('mine')
    expect(initialTab(rows, null)).toBe('mine')
    expect(initialTab([rows[0]], 'zz')).toBe('shared')
  })
  it('复制的新编号不重名', () => {
    expect(copyId('x', [])).toBe('x-copy')
    expect(copyId('x', ['x-copy', 'x-copy-2'])).toBe('x-copy-3')
  })
  it('编号规则与后端一致', () => {
    expect(validAssetId('cisco-asr920.v2_a')).toBe(true)
    expect(validAssetId('-x')).toBe(false)
    expect(validAssetId('中文')).toBe(false)
    expect(validAssetId('a'.repeat(81))).toBe(false)
  })
})
