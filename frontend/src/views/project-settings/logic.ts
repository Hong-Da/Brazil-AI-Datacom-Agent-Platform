/** 项目设置页的纯逻辑：检查规则调整（REQ-036）的行状态与请求体、设置的差异。 */

export type Severity = 'error' | 'warning' | 'info'
export const SEVERITIES: Severity[] = ['error', 'warning', 'info']

/** GET /projects/{p}/rules 的一行。 */
export interface RuleRow {
  id: string
  builtin?: boolean | null
  title: Record<string, string> | string | null
  severity: Severity
  enabled: boolean
  domain: string | null
  tags?: string[] | null
  ai?: boolean | null
  override: { rule: string; enabled: boolean; severity: Severity | null; reason: string; updated_by?: string | null; updated_at?: string | null } | null
  effective: { enabled: boolean; severity: Severity }
}

/** 编辑中的一行（开关、级别、原因）。 */
export interface RuleDraft { enabled: boolean; severity: Severity; reason: string }

export function draftOf(r: RuleRow): RuleDraft {
  return {
    enabled: r.override ? r.override.enabled : true,
    severity: r.override?.severity ?? r.severity,
    reason: r.override?.reason ?? '',
  }
}

/** 草稿与已保存的状态不同（需要保存）。 */
export function isDirty(r: RuleRow, d: RuleDraft): boolean {
  const cur = draftOf(r)
  return cur.enabled !== d.enabled || cur.severity !== d.severity || cur.reason.trim() !== d.reason.trim()
}

/** 草稿等于共享设置（没有调整）：保存时改为“恢复共享设置”。 */
export function isShared(r: RuleRow, d: RuleDraft): boolean {
  return d.enabled && d.severity === r.severity
}

/** PUT /projects/{p}/rules/{rule} 的请求体：级别与共享相同时不传（null，跟随共享）。 */
export function overrideBody(r: RuleRow, d: RuleDraft): { enabled: boolean; severity: Severity | null; reason: string } {
  return { enabled: d.enabled, severity: d.severity === r.severity ? null : d.severity, reason: d.reason.trim() }
}

/** 行的标记：本项目关闭 / 本项目调整 / 无。 */
export function overrideMark(r: RuleRow): 'off' | 'adjusted' | null {
  if (!r.override) return null
  return r.override.enabled ? 'adjusted' : 'off'
}

export interface SettingsForm { name: string; slug: string; description: string; style: string; rule_set: string; baseline: string }

/** PUT /projects/{p} 的请求体：只带变化的字段（标识没变时不传，避免可编辑成员被拒）。 */
export function settingsPatch(orig: SettingsForm, cur: SettingsForm): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  if (cur.name.trim() !== orig.name) out.name = cur.name.trim()
  if (cur.slug.trim() !== orig.slug) out.slug = cur.slug.trim()
  if (cur.description !== orig.description) out.description = cur.description
  const settings: Record<string, string> = {}
  for (const k of ['style', 'rule_set', 'baseline'] as const) if (cur[k] !== orig[k]) settings[k] = cur[k]
  if (Object.keys(settings).length) out.settings = settings
  return out
}
