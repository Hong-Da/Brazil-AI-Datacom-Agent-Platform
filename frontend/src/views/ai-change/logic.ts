/**
 * 变更与割接组 AI skill 的页面接入（M8-4，预览 DevelopDocs/ui-preview/M8/change.html）：范围键、流程条的当前步、
 * 割接迁移请求 → skill 参数、翻译结果里的 AI 写法、割接方案文档的段落状态。组件只负责显示与交互。
 */

/** 与后端 core/ai_suggest_change.py 的 scope_key 一致（面板按它取建议）。 */
export const scopes = {
  intent: (device: number) => `change:${device}`,
  cutover: (device: number, to: string) => `cutover:${device}:${to}`,
  translate: (device: number, to: string) => `translate:${device}:${to}`,
  naming: (device: number, to: string) => `naming:${device}:${to}`,
  template: (devices: number[]) => `template:${[...devices].sort((a, b) => a - b).join(',')}`,
}

export type FlowKey = 'nl' | 'edit' | 'script' | 'impact' | 'sim'
export interface FlowStep { k: FlowKey; icon: string; kind: '' | 'ai' | 'code'; cur: boolean }
/** 流程条：自然语言 → 目标图改动（AI）→ 变更脚本 / 影响分析 / 模拟执行（代码）。有采纳时代码三步都是当前步。 */
export function flowSteps(panelState: string, adopted: number): FlowStep[] {
  const ran = !['idle', 'loading', 'off', 'error'].includes(panelState)
  return [
    { k: 'nl', icon: 'chat', kind: '', cur: !ran },
    { k: 'edit', icon: 'spark', kind: 'ai', cur: ran && !adopted },
    { k: 'script', icon: 'terminal', kind: 'code', cur: adopted > 0 },
    { k: 'impact', icon: 'target', kind: 'code', cur: adopted > 0 },
    { k: 'sim', icon: 'play', kind: 'code', cur: adopted > 0 },
  ]
}

export interface PlanRow { text: string; k: string; seq: number | null }
export interface ChangePlan {
  batch_id: number
  adopted: number[]
  intent?: string
  rows?: PlanRow[]
  script?: string
  rollback?: string
  impact?: { objects?: number; business?: number; seeds?: number }
  risk?: { level: string }
  verify?: boolean
  rollback_verify?: boolean
  summary?: { ops: number }
  reasons?: { code: string; level: string; ref?: string; detail?: string }[]
  script_info?: { group_id: number; script_id: number; rollback_id?: number } | null
}

/** 割接迁移页的请求体 → cutover-plan / naming-map 的参数（与 /migrate 同一组输入，结果由代码重新计算）。 */
export function cutoverParams(body: Record<string, unknown> | null): Record<string, unknown> | null {
  if (!body || body.device_id == null || !body.to) return null
  const out: Record<string, unknown> = { device_id: body.device_id, to: body.to }
  for (const k of ['interface_map', 'on_conflict', 'rule_set', 'model', 'target_device_id']) {
    if (body[k] != null && body[k] !== '') out[k] = body[k]
  }
  return out
}

export interface Unsupported { kind: string; key: string; node?: string | null; schema?: string | null; lines?: number[]; params?: Record<string, unknown>; ai?: { suggestion_id: number; kind: string; config: string } }
export interface GapRow { line: number; kind: string; schema: string; text: string; ai: Unsupported['ai'] | null }
/** 翻译结果里不支持 / 原文保留的项（每个起始行一条），带上已采纳的 AI 写法。密码类不列（人工重新设置）。 */
export function gapRows(items: Unsupported[] | undefined): GapRow[] {
  const seen = new Set<number>()
  const out: GapRow[] = []
  for (const u of items ?? []) {
    const line = u.lines?.[0]
    if (line == null || seen.has(line) || u.params?.reason === 'secret') continue
    seen.add(line)
    out.push({ line, kind: u.kind, schema: u.schema ?? '', text: String(u.params?.text ?? u.node ?? ''), ai: u.ai ?? null })
  }
  return out.sort((a, b) => a.line - b.line)
}

/** 译文中来自 AI 的行号集合（界面标紫）。 */
export function aiLineSet(lines: number[] | undefined): Set<number> {
  return new Set(lines ?? [])
}

export interface DocPart { suggestion_id: number; status: string; text: string; steps: { step: string; label: string; action: string; commands: string[]; check: string }[] }
export interface DocSection { section: string; title: string; parts: DocPart[] }
export interface PlanDoc { lang: string; title: string; meta: string; note: string; sections: DocSection[]; steps: { ref: string; no: number; phase: string; side: string; label: string; commands: string[] }[]; batch_id: number }
/** 一节的显示状态：adopted 已采纳、pending 待采纳、missing 没有可用的内容（需人工填写）。 */
export function sectionState(sec: DocSection): 'adopted' | 'pending' | 'missing' {
  if (sec.parts.some((p) => p.status === 'adopted')) return 'adopted'
  if (sec.parts.some((p) => p.status === 'pending')) return 'pending'
  return 'missing'
}
/** 文档语言：中文界面看中文版，其余看英文版（报告中英双语）。 */
export function docLang(uiLang: string): 'zh-CN' | 'en' {
  return uiLang === 'zh-CN' ? 'zh-CN' : 'en'
}

/** 模板提取：选中 1～10 台同一平台族的设备才能运行。 */
export function templateReady(ids: number[], families: string[]): boolean {
  return ids.length >= 1 && ids.length <= 10 && new Set(families).size <= 1
}
