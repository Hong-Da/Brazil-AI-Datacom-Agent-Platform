import { describe, expect, it } from 'vitest'
import { activity, avatars, confirmMatches, matchProject, projectAbilities, projectBody, sortProjects, suggestSlug, validSlug } from './logic'
import { draftOf, isDirty, isShared, overrideBody, overrideMark, settingsPatch, type RuleRow } from '../project-settings/logic'
import { markUpgradeSeen, migratedProjects, shouldShowUpgrade } from '@/project/upgrade'

describe('我的项目', () => {
  it('按名称、标识、属主搜索', () => {
    const p = { name: '城域 OAM', slug: 'oam-vpn', owner: 'liwei' }
    expect(matchProject(p, '')).toBe(true)
    expect(matchProject(p, 'OAM')).toBe(true)
    expect(matchProject(p, 'liw')).toBe(true)
    expect(matchProject(p, 'bgp')).toBe(false)
  })
  it('标识规则与建议', () => {
    expect(validSlug('oam-vpn')).toBe(true)
    expect(validSlug('a')).toBe(false)
    expect(validSlug('-ab')).toBe(false)
    expect(validSlug('Oam')).toBe(false)
    expect(suggestSlug('ATN 割接 2026Q4')).toBe('atn-2026q4')
    expect(suggestSlug('默认项目')).toBe('')
    expect(suggestSlug('Configuração  Básica')).toBe('configuracao-basica')
  })
  it('排序：最近活动在前，或按名称', () => {
    const rows = [
      { name: 'b', updated_at: '2026-10-01T00:00:00Z', last_activity: null },
      { name: 'a', updated_at: '2026-09-01T00:00:00Z', last_activity: { at: '2026-10-05T00:00:00Z' } },
    ]
    expect(sortProjects(rows, 'act').map((r) => r.name)).toEqual(['a', 'b'])
    expect(sortProjects(rows, 'name').map((r) => r.name)).toEqual(['a', 'b'])
    expect(rows[0].name).toBe('b')
  })
  it('按角色能做的事', () => {
    expect(projectAbilities('owner')).toEqual({ edit: true, manage: true, leave: false })
    expect(projectAbilities('edit')).toEqual({ edit: true, manage: false, leave: true })
    expect(projectAbilities('read')).toEqual({ edit: false, manage: false, leave: true })
    expect(projectAbilities('admin')).toEqual({ edit: true, manage: true, leave: false })
    expect(projectAbilities('owner', true)).toEqual({ edit: false, manage: false, leave: false })
  })
  it('删除确认、请求体、头像', () => {
    expect(confirmMatches(' oam ', 'oam')).toBe(true)
    expect(confirmMatches('Oam', 'oam')).toBe(false)
    expect(projectBody(' X ', '')).toEqual({ name: 'X' })
    expect(projectBody('X', 'Ab-1', { settings: { style: 'cisco' } })).toEqual({ name: 'X', slug: 'ab-1', settings: { style: 'cisco' } })
    expect(avatars('o', ['o', 'a', 'b'], 2)).toEqual(['o', 'a'])
  })
  it('最近活动映射', () => {
    expect(activity(null)).toBeNull()
    expect(activity({ actor: 'u', action: 'POST /configs', at: 't' })?.key).toBe('import')
    expect(activity({ action: 'PATCH /x', at: 't' })).toEqual({ key: null, raw: 'PATCH /x', actor: '', at: 't' })
  })
})

describe('项目设置：规则调整', () => {
  const row = (o: RuleRow['override'] = null): RuleRow => ({ id: 'r', title: 'R', severity: 'warning', enabled: true, domain: null, override: o, effective: { enabled: true, severity: 'warning' } })
  it('草稿与保存', () => {
    const r = row()
    const d = draftOf(r)
    expect(d).toEqual({ enabled: true, severity: 'warning', reason: '' })
    expect(isDirty(r, d)).toBe(false)
    expect(isShared(r, d)).toBe(true)
    const d2 = { ...d, severity: 'info' as const, reason: ' 实验局 ' }
    expect(isDirty(r, d2)).toBe(true)
    expect(isShared(r, d2)).toBe(false)
    expect(overrideBody(r, d2)).toEqual({ enabled: true, severity: 'info', reason: '实验局' })
    expect(overrideBody(r, { enabled: false, severity: 'warning', reason: 'x' })).toEqual({ enabled: false, severity: null, reason: 'x' })
  })
  it('标记', () => {
    expect(overrideMark(row())).toBeNull()
    expect(overrideMark(row({ rule: 'r', enabled: false, severity: null, reason: 'x' }))).toBe('off')
    expect(overrideMark(row({ rule: 'r', enabled: true, severity: 'info', reason: 'x' }))).toBe('adjusted')
  })
  it('设置只带变化的字段', () => {
    const o = { name: 'A', slug: 'a', description: '', style: '', rule_set: '', baseline: '' }
    expect(settingsPatch(o, { ...o })).toEqual({})
    expect(settingsPatch(o, { ...o, name: ' B ', style: 'cisco' })).toEqual({ name: 'B', settings: { style: 'cisco' } })
  })
})

describe('升级说明', () => {
  const mem = (): Storage => {
    const m = new Map<string, string>()
    return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v) } as unknown as Storage
  }
  it('有迁移来的项目且没看过才显示，看过后不再显示', () => {
    const s = mem()
    const lists = { mine: [{ migrated_from: { type: 'upgrade' } }, { migrated_from: null }] }
    expect(migratedProjects(lists.mine)).toHaveLength(1)
    expect(shouldShowUpgrade('u', { mine: [{ migrated_from: null }] }, s)).toBe(false)
    expect(shouldShowUpgrade('u', lists, s)).toBe(true)
    markUpgradeSeen('u', s)
    expect(shouldShowUpgrade('u', lists, s)).toBe(false)
    expect(shouldShowUpgrade('v', lists, s)).toBe(true)
    expect(shouldShowUpgrade(null, lists, s)).toBe(false)
  })
})
