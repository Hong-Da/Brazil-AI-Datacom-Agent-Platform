/**
 * 添加设备到项目（REQ-035，预览 DevelopDocs/ui-preview/M6/add-device.html）的纯逻辑：
 * 公共设备是否已在项目里、复制后的名称（同名自动加 -2、-3，与后端 copy_device 一致）、
 * 把选择整理成逐条要调用的操作（没有批量接口）、底部汇总、导入结果分类。
 */

export interface PubRef { project: string; full_ref?: string; name: string; owner: string | null; policy: 'follow' | 'pin'; version_id: number | null; seq: number | null }
export interface PubDevice {
  id: number
  name: string
  vendor: string
  sw_version: string
  profile: string
  versions: number
  latest_version_id: number | null
  collected_at: string | null
  refs: PubRef[]
  follow: number
  pinned: number
}
/** 项目里的设备（GET /projects/{p}/devices 的一行，只用到这些字段）。 */
export interface ProjDevice {
  id: number
  name: string
  vendor: string
  sw_version?: string
  profile: string
  versions: number
  latest_version_id: number | null
  source?: string
  policy?: string
  pinned_seq?: number | null
}
export interface Version { id: number; seq: number; collected_at: string | null; latest?: boolean; current?: boolean }

/** 公共设备的选择：引用（跟随最新 / 固定版本）或复制为私有（复制哪个版本）。 */
export interface PubSel { mode: 'ref' | 'copy'; policy: 'follow' | 'pin'; versionId: number | null }
/** 其他项目设备的选择：复制哪个版本（null = 来源项目里的当前版本）、复制后的名称。 */
export interface ProjSel { versionId: number | null; name: string }

/** 公共设备已经在本项目里：已引用（同一编号）或有同名设备（引用会 409）。 */
export function inProject(d: { id: number; name: string }, here: ProjDevice[]): 'ref' | 'name' | null {
  if (here.some((x) => x.id === d.id)) return 'ref'
  const n = d.name.toLowerCase()
  if (here.some((x) => x.name.toLowerCase() === n)) return 'name'
  return null
}

/** 复制后的名称：没有重名就用原名，否则 name-2、name-3…（taken 不区分大小写）。 */
export function predictName(name: string, taken: Iterable<string>): string {
  const set = new Set([...taken].map((x) => x.toLowerCase()))
  if (!set.has(name.toLowerCase())) return name
  for (let i = 2; ; i++) {
    const c = `${name}-${i}`
    if (!set.has(c.toLowerCase())) return c
  }
}

export interface Op {
  kind: 'ref' | 'copy'
  deviceId: number
  versionId: number | null
  name?: string
  /** 显示用：设备名与来源 */
  label: string
  from: 'public' | string
}

/** 把两种选择整理成逐条操作：先引用，再复制（复制的名称按顺序避开前面已占用的名字由后端处理）。 */
export function buildOps(
  pub: PubDevice[],
  pubSel: Record<number, PubSel>,
  srcProject: string | null,
  srcDevices: ProjDevice[],
  projSel: Record<number, ProjSel>,
): Op[] {
  const ops: Op[] = []
  for (const d of pub) {
    const s = pubSel[d.id]
    if (!s) continue
    if (s.mode === 'ref') ops.push({ kind: 'ref', deviceId: d.id, versionId: s.policy === 'pin' ? s.versionId : null, label: d.name, from: 'public' })
  }
  for (const d of pub) {
    const s = pubSel[d.id]
    if (s?.mode === 'copy') ops.push({ kind: 'copy', deviceId: d.id, versionId: s.versionId, label: d.name, from: 'public' })
  }
  if (srcProject) {
    for (const d of srcDevices) {
      const s = projSel[d.id]
      if (!s) continue
      const name = s.name.trim()
      ops.push({ kind: 'copy', deviceId: d.id, versionId: s.versionId, name: name && name !== d.name ? name : undefined, label: d.name, from: srcProject })
    }
  }
  return ops
}

export interface Summary { refFollow: number; refPin: number; copies: number; files: number }

export function summarize(ops: Op[], files: number): Summary {
  return {
    refFollow: ops.filter((o) => o.kind === 'ref' && o.versionId === null).length,
    refPin: ops.filter((o) => o.kind === 'ref' && o.versionId !== null).length,
    copies: ops.filter((o) => o.kind === 'copy').length,
    files,
  }
}

export interface ImportResult { source: string; ok: boolean; device: string; error?: string; duplicate?: boolean; version_id?: number | null }
export type ImportKind = 'new' | 'version' | 'duplicate' | 'failed'

/** 导入结果分类：新私有设备 / 已有设备的新版本 / 与最新版本相同 / 失败（同一批里同名的第二个文件算新版本）。 */
export function classifyImport(results: ImportResult[], before: ProjDevice[]): ImportKind[] {
  const seen = new Set(before.map((d) => d.name.toLowerCase()))
  return results.map((r) => {
    if (!r.ok) return 'failed'
    if (r.duplicate) return 'duplicate'
    const n = r.device.toLowerCase()
    if (seen.has(n)) return 'version'
    seen.add(n)
    return 'new'
  })
}

/** 按名称、型号、Profile 筛选。 */
export function matchDevice(d: { name: string; profile: string; sw_version?: string; vendor?: string }, q: string): boolean {
  const k = q.trim().toLowerCase()
  if (!k) return true
  return [d.name, d.profile, d.sw_version ?? '', d.vendor ?? ''].join(' ').toLowerCase().includes(k)
}
