import { describe, expect, it } from 'vitest'
import type { ProjectRow } from '@/stores/project'
import { auditAction, auditDetail, groupByOwner, isIdle, projectsCsv } from './logic'

const NOW = Date.parse('2026-10-19T12:00:00Z')
const p = (slug: string, owner: string | null, extra: Partial<ProjectRow> = {}): ProjectRow => ({
  id: 1, slug, name: slug.toUpperCase(), description: '', owner, role: 'admin', members: 1, member_names: owner ? [owner] : [],
  settings: {}, last_activity: null, counts: { devices: 0, private: 0, refs: 0, scripts: 0, scripts_with_errors: 0, check_projects: 0 },
  created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-18T00:00:00Z', ...extra,
})

describe('all-projects logic', () => {
  const rows = [
    p('b1', 'bob'),
    p('a1', 'admin'),
    p('old', 'carol', { owner_disabled: true, updated_at: '2026-05-01T00:00:00Z' }),
    p('orphan', null),
    p('b2', 'bob', { member_names: ['bob', 'liwei'] }),
  ]

  it('groupByOwner：自己在前，没有属主在最后', () => {
    const g = groupByOwner(rows, 'admin', '', '', NOW)
    expect(g.map((x) => [x.owner, x.projects.length])).toEqual([['admin', 1], ['bob', 2], ['carol', 1], ['', 1]])
    expect(g[2].disabled).toBe(true)
  })

  it('筛选：属主已停用、90 天无活动、按成员搜索', () => {
    expect(groupByOwner(rows, 'admin', '', 'disabled', NOW).map((x) => x.owner)).toEqual(['carol'])
    expect(groupByOwner(rows, 'admin', '', 'idle', NOW).map((x) => x.owner)).toEqual(['carol'])
    expect(groupByOwner(rows, 'admin', 'LIWEI', '', NOW).flatMap((x) => x.projects.map((y) => y.slug))).toEqual(['b2'])
  })

  it('isIdle 优先看最近活动', () => {
    expect(isIdle(p('x', 'u', { updated_at: '2026-01-01T00:00:00Z', last_activity: { at: '2026-10-10T00:00:00Z', action: 'POST /configs' } }), NOW)).toBe(false)
  })

  it('projectsCsv：带 BOM，含逗号与引号的值加引号', () => {
    const csv = projectsCsv([p('x', 'u', { name: 'A, "B"' })], ['name', 'slug', 'owner', 'disabled', 'members', 'devices', 'private', 'refs', 'scripts', 'activity'])
    expect(csv.charCodeAt(0)).toBe(0xfeff)
    const lines = csv.slice(1).split('\r\n')
    expect(lines[1]).toBe('"A, ""B""",x,u,,u,0,0,0,0,2026-10-18T00:00:00Z')
  })

  it('审计动作与说明', () => {
    expect(auditAction('enter')).toBe('enter')
    expect(auditAction('other')).toBeNull()
    expect(auditDetail({ method: 'GET', path: '' })).toBe('GET /')
    expect(auditDetail({ method: 'PUT', path: '/rules/{rule_id}' })).toBe('PUT /rules/{rule_id}')
    expect(auditDetail({ project_id: 3 })).toBe('project_id=3')
    expect(auditDetail(null)).toBe('')
  })
})
