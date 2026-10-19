import { describe, expect, it } from 'vitest'
import { canConfirm, deletePath, planDelete, projectList, type DeletePreview, type DelProject } from './deleteLogic'

const proj = (id: number, version_id: number | null, scripts: string[] = []): DelProject => ({
  id, name: `P${id}`, version_id, follows_latest: version_id === null, scripts: scripts.map((n, i) => ({ id: i + 1, name: n, kind: 'change' })),
})

function preview(projects: DelProject[] = [], n = 3): DeletePreview {
  return {
    device: { id: 7, name: 'R1', vendor: 'huawei', profile: 'p' },
    counts: { versions: n, imports: n + 1, nodes: 500, edges: 400, unknown_lines: 2, check_ignores: 1 },
    baseline: { projects, scripts: projects.reduce((s, p) => s + p.scripts.length, 0) },
    versions: Array.from({ length: n }, (_, i) => ({ id: 10 + i, seq: i + 1, latest: i === n - 1, collected_at: null, tag: null, imports: i === 0 ? 2 : 1, pinned_by: projects.filter((p) => p.version_id === 10 + i).map((p) => p.id) })),
    blocked: projects.length > 0,
  }
}

describe('planDelete（删除设备）', () => {
  it('列出连带删除的内容与数量', () => {
    const plan = planDelete(preview())
    expect(plan.mode).toBe('device')
    expect(plan.rows.map((r) => [r.label, r.n])).toEqual([['rowVersions', 3], ['rowGraph', 500], ['rowUnknown', 2], ['rowIgnores', 1], ['rowImports', 4]])
    expect(plan.blockers).toEqual([])
    expect(canConfirm(plan, false)).toBe(true)
  })
  it('作基线的项目阻止删除，勾选 force 后可以删除', () => {
    const plan = planDelete(preview([proj(1, null, ['a', 'b'])]))
    expect(plan.blockers.map((p) => p.id)).toEqual([1])
    expect(canConfirm(plan, false)).toBe(false)
    expect(canConfirm(plan, true)).toBe(true)
  })
})

describe('planDelete（删除版本）', () => {
  it('删除最新版本：跟随最新的项目改用上一个版本，只提示不阻止', () => {
    const plan = planDelete(preview([proj(1, null), proj(2, 10)]), 12)
    expect(plan.version?.seq).toBe(3)
    expect(plan.nextLatest?.id).toBe(11)
    expect(plan.moved.map((p) => p.id)).toEqual([1])
    expect(plan.blockers).toEqual([])
    expect(plan.rows.find((r) => r.label === 'rowOthers')?.n).toBe(2)
    expect(canConfirm(plan, false)).toBe(true)
  })
  it('固定为基线的版本需要 force；较早的版本不影响跟随最新的项目', () => {
    const plan = planDelete(preview([proj(1, null), proj(2, 10)]), 10)
    expect(plan.blockers.map((p) => p.id)).toEqual([2])
    expect(plan.moved).toEqual([])
    expect(plan.nextLatest).toBeNull()
    expect(plan.rows.find((r) => r.label === 'rowThisImports')?.n).toBe(2)
    expect(canConfirm(plan, false)).toBe(false)
    expect(canConfirm(plan, true)).toBe(true)
  })
  it('最后一个版本不能单独删除', () => {
    const plan = planDelete(preview([], 1), 10)
    expect(plan.lastVersion).toBe(true)
    expect(canConfirm(plan, true)).toBe(false)
  })
  it('版本不存在时不能确认', () => {
    expect(canConfirm(planDelete(preview(), 99), true)).toBe(false)
  })
})

describe('辅助函数', () => {
  it('项目列表与请求路径', () => {
    expect(projectList([proj(1, null, ['a', 'b']), proj(2, 3)])).toBe('P1（a、b）、P2')
    expect(deletePath(7, null, false)).toBe('/devices/7')
    expect(deletePath(7, 12, true)).toBe('/devices/7/versions/12?force=true')
  })
})
