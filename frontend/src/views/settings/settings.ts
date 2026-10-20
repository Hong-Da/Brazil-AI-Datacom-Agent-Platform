/** 系统设置页（REQ-049）的纯逻辑：数据来自 GET /settings（后端 core/setup.py 的 settings_view）。 */
import type { WField } from '../wizard/wizard'

/** readonly：env 由环境变量指定 / ai 在 AI 接口页管理 / secret 敏感值；null 可以修改 */
export interface SField extends WField {
  value: string | number | boolean
  source: string
  restart: boolean
  readonly: 'env' | 'ai' | 'secret' | null
}
export interface SGroup { id: string; title: string; fields: SField[] }
export interface Pending { key: string; running: string | number | boolean; saved: string | number | boolean }
export interface SettingsData { groups: SGroup[]; config_path: string; restart_pending: Pending[]; running: Record<string, string | number> }

/** 控件类型：敏感值只显示是否已设置；选项与开关用下拉；其余输入框。 */
export function controlOf(f: SField): 'secret' | 'select' | 'input' {
  if (f.secret) return 'secret'
  if (f.kind === 'choice' || f.kind === 'bool') return 'select'
  return 'input'
}

/** 和当前值不同的修改（按字符串比较：输入框里的 "9090" 与 9090 相同）。 */
export function changedKeys(groups: SGroup[], edits: Record<string, string | number>): string[] {
  const out: string[] = []
  for (const g of groups) for (const f of g.fields) if (f.key in edits && String(edits[f.key]) !== String(f.value ?? '')) out.push(f.key)
  return out
}

/** 待重启列表里的取值：敏感值是布尔（是否已设置）。 */
export function pendingText(v: string | number | boolean, set: string, unset: string): string {
  if (typeof v === 'boolean') return v ? set : unset
  return String(v)
}
