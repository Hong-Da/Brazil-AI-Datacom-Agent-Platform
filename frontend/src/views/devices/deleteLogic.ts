/**
 * 删除设备 / 删除单个配置版本（REQ-038）的确认框数据：由 GET /devices/{id}/delete-preview 的结果算出
 * 连带删除的内容、受影响的配置检查项目与脚本、是否需要勾选“仍然删除”（force）、能否删除。
 */

export interface DelProject {
  id: number
  name: string
  version_id: number | null
  follows_latest: boolean
  scripts: { id: number; name: string; kind: string }[]
}

export interface DelVersion {
  id: number
  seq: number
  latest: boolean
  collected_at: string | null
  tag: string | null
  imports: number
  pinned_by: number[]
}

export interface DeletePreview {
  device: { id: number; name: string; vendor: string; profile: string }
  counts: { versions: number; imports: number; nodes: number; edges: number; unknown_lines: number; check_ignores: number }
  baseline: { projects: DelProject[]; scripts: number }
  versions: DelVersion[]
  blocked: boolean
}

/** 确认框里的一行：del 删除 / keep 保留；label 是文案键（devdel.*），n 是数量（null 不显示）。 */
export interface ImpactRow { kind: 'del' | 'keep'; icon: string; label: string; n: number | string | null }

export interface DeletePlan {
  mode: 'device' | 'version'
  rows: ImpactRow[]
  /** 不加 force 会被拒绝的项目（设备：以它为基线的全部项目；版本：固定这个版本的项目）。 */
  blockers: DelProject[]
  /** 删除最新版本时，跟随最新版本的项目会改用上一个版本（只提示，不阻止）。 */
  moved: DelProject[]
  /** 最后一个版本不能单独删除。 */
  lastVersion: boolean
  version: DelVersion | null
  /** 删除后的最新版本（删除版本时）。 */
  nextLatest: DelVersion | null
}

export function planDelete(p: DeletePreview, versionId: number | null = null): DeletePlan {
  if (versionId === null) {
    const c = p.counts
    return {
      mode: 'device',
      rows: [
        { kind: 'del', icon: 'history', label: 'rowVersions', n: c.versions },
        { kind: 'del', icon: 'graph', label: 'rowGraph', n: c.nodes },
        { kind: 'del', icon: 'unknown', label: 'rowUnknown', n: c.unknown_lines },
        { kind: 'del', icon: 'inbox', label: 'rowIgnores', n: c.check_ignores },
        { kind: 'del', icon: 'file', label: 'rowImports', n: c.imports },
      ],
      blockers: p.baseline.projects,
      moved: [],
      lastVersion: false,
      version: null,
      nextLatest: null,
    }
  }
  const idx = p.versions.findIndex((v) => v.id === versionId)
  const v = idx >= 0 ? p.versions[idx] : null
  const lastVersion = p.versions.length <= 1
  const others = p.versions.filter((x) => x.id !== versionId)
  const nextLatest = v?.latest ? others[others.length - 1] ?? null : null
  return {
    mode: 'version',
    rows: [
      { kind: 'del', icon: 'history', label: 'rowThisVersion', n: v ? `#${v.seq}` : null },
      { kind: 'del', icon: 'graph', label: 'rowThisGraph', n: null },
      { kind: 'del', icon: 'file', label: 'rowThisImports', n: v?.imports ?? 0 },
      { kind: 'keep', icon: 'history', label: 'rowOthers', n: others.length },
    ],
    blockers: v ? p.baseline.projects.filter((x) => x.version_id === v.id) : [],
    moved: v?.latest && !lastVersion ? p.baseline.projects.filter((x) => x.follows_latest) : [],
    lastVersion,
    version: v,
    nextLatest,
  }
}

/** 项目与脚本的简短列表：“项目（脚本 1、脚本 2）”，多个项目用顿号分隔。 */
export function projectList(ps: DelProject[], sep = '、'): string {
  return ps.map((p) => (p.scripts.length ? `${p.name}（${p.scripts.map((s) => s.name).join(sep)}）` : p.name)).join(sep)
}

/** 删除请求的路径。 */
export function deletePath(deviceId: number, versionId: number | null, force: boolean): string {
  const base = versionId === null ? `/devices/${deviceId}` : `/devices/${deviceId}/versions/${versionId}`
  return force ? `${base}?force=true` : base
}

/** 确认按钮是否可用：不是最后一个版本，有阻止删除的项目时必须勾选 force。 */
export function canConfirm(plan: DeletePlan, force: boolean): boolean {
  if (plan.lastVersion) return false
  if (plan.mode === 'version' && !plan.version) return false
  return !plan.blockers.length || force
}
