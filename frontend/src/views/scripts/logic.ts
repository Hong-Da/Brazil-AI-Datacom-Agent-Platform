/** 项目脚本页（M6，原“配置检查项目”并入项目）的数据结构与纯逻辑：筛选、基线设备的来源与版本、新脚本的初始内容。 */

export type Kind = 'change' | 'full'

/** GET /projects/{p}/scripts 的一行。 */
export interface ScriptRow {
  id: number
  project_id: number
  name: string
  kind: Kind
  lines: number
  revisions: number
  last_check: { errors: number; warnings: number; infos: number; order: boolean | null; kind: Kind; at: string } | null
  created_at: string | null
  updated_at: string | null
  group: { id: number; name: string }
  baseline: {
    device: { id: number; name: string; vendor: string; platform?: string; profile: string } | null
    version_id: number | null
    follows_latest: boolean
  } | null
  order_check: boolean | null
  ai_check: boolean
  author: string | null
}

/** 当前项目设备列表（GET /devices）里用到的字段。 */
export interface ProjDevice {
  id: number
  name: string
  vendor: string
  profile: string
  versions: number
  latest_version_id: number | null
  source?: 'private' | 'public'
  policy?: 'follow' | 'pin'
  pinned_version_id?: number | null
  pinned_seq?: number | null
  newer_available?: boolean
}

export interface ScriptFilter { kind: '' | Kind; device: number | null }

export function filterScripts(rows: ScriptRow[], f: ScriptFilter): ScriptRow[] {
  return rows.filter((r) => (!f.kind || r.kind === f.kind) && (f.device === null || r.baseline?.device?.id === f.device))
}

/** 基线设备在本项目里的标记：来源（私有 / 公共）、版本策略、显示的版本序号。 */
export interface BaseMark { source: 'private' | 'public'; policy: 'follow' | 'pin'; seq: number | null; latestSeq: number | null; newer: boolean }

/**
 * 脚本跟随基线设备的“当前版本”时，序号来自项目对它的版本策略（公共设备固定时为 pinned_seq，否则为最新）；
 * 脚本自己指定了版本时用 verSeq（版本编号 → 序号）查。
 */
export function baseMark(row: ScriptRow, dev: ProjDevice | undefined, verSeq: Record<number, number>): BaseMark | null {
  if (!row.baseline?.device) return null
  const source = dev?.source === 'public' ? 'public' : 'private'
  const devPinned = source === 'public' && dev?.policy === 'pin'
  const latestSeq = dev ? dev.versions : null
  if (row.baseline.version_id !== null) {
    return { source, policy: 'pin', seq: verSeq[row.baseline.version_id] ?? null, latestSeq, newer: false }
  }
  if (devPinned) {
    const seq = dev?.pinned_seq ?? (dev?.pinned_version_id ? verSeq[dev.pinned_version_id] : undefined) ?? null
    return { source, policy: 'pin', seq, latestSeq, newer: !!dev?.newer_available }
  }
  return { source, policy: 'follow', seq: latestSeq, latestSeq, newer: false }
}

/** 最近检查：never 未检查、ok 无问题、issues 有问题。 */
export function checkState(c: ScriptRow['last_check']): 'never' | 'ok' | 'issues' {
  if (!c) return 'never'
  return c.errors || c.warnings || c.infos ? 'issues' : 'ok'
}

/** 新建变更脚本的初始内容：按平台给出进入 / 提交配置的框架。 */
export function starterChange(vendorOrProfile: string): string {
  return vendorOrProfile.toLowerCase().startsWith('cisco') ? 'configure terminal\n\nend\n' : 'system-view\n\ncommit\n'
}

/** 默认文件名：script-<n>.txt，避开已有的名称。 */
export function nextScriptName(rows: { name: string }[]): string {
  const names = new Set(rows.map((r) => r.name))
  let n = rows.length + 1
  while (names.has(`script-${n}.txt`)) n++
  return `script-${n}.txt`
}

/** 一次性说明是否已关闭（浏览器本地记住）。 */
export const NOTE_KEY = 'lmesh-scripts-merge-note'
