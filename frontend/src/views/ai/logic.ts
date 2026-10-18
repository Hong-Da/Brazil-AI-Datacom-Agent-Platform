/** AI 接口页面的纯逻辑：表单与保存内容、来源（环境变量只读）、调用记录汇总。 */

import { parseIso } from '../ingest/logic'

export const PROVIDERS = ['anthropic', 'openai', 'local'] as const
export type Provider = '' | (typeof PROVIDERS)[number]

export const FIELDS = ['provider', 'base_url', 'model', 'model_extract', 'model_merge', 'timeout', 'max_tokens'] as const
export type Field = (typeof FIELDS)[number]

/** GET /ai/settings 的返回。 */
export interface AiSettings {
  provider: Provider
  base_url: string
  model: string
  model_extract: string
  model_merge: string
  timeout: number
  max_tokens: number
  api_key_set: boolean
  sources: Record<string, string>
}

export interface AiForm {
  provider: Provider
  base_url: string
  model: string
  model_extract: string
  model_merge: string
  timeout: number
  max_tokens: number
}

export interface AiStatus { configured: boolean; provider: string; models: Record<string, string> }

export interface AiCall {
  id: number
  task: string
  provider: string
  model: string
  tokens_in: number | null
  tokens_out: number | null
  status: string
  error: string | null
  review_item_id: number | null
  created_at: string | null
}

/** 取值范围与后端 config.FIELDS 一致。 */
export const LIMITS = { timeout: [5, 600], max_tokens: [256, 200000] } as const

export function formFrom(s: AiSettings): AiForm {
  return {
    provider: s.provider || '',
    base_url: s.base_url || '',
    model: s.model || '',
    model_extract: s.model_extract || '',
    model_merge: s.model_merge || '',
    timeout: Number(s.timeout) || 60,
    max_tokens: Number(s.max_tokens) || 4096,
  }
}

/** 由环境变量设置的项：界面只读，保存时不提交。 */
export function isEnv(sources: Record<string, string> | undefined, key: string): boolean {
  return sources?.[key] === 'env'
}

/** 环境变量名（与 lmesh.core.config.env_name 一致）。 */
export function envName(key: string): string {
  return `LMESH_AI__${key.toUpperCase()}`
}

export function needsBaseUrl(p: Provider): boolean {
  return p === 'openai' || p === 'local'
}

/** 本地模型通常不需要 API Key。 */
export function usesKey(p: Provider): boolean {
  return p === 'anthropic' || p === 'openai'
}

/** 表单问题：{字段: 文案键（相对 ai-settings.）}。 */
export function validateAi(f: AiForm, keySet: boolean, keyInput: string, clearKey: boolean): Partial<Record<Field | 'api_key', string>> {
  const out: Partial<Record<Field | 'api_key', string>> = {}
  if (!f.provider) return out // 不使用 AI：其余项不检查
  if (needsBaseUrl(f.provider) && !f.base_url.trim()) out.base_url = 'errBaseUrl'
  else if (f.base_url.trim() && !/^https?:\/\/\S+$/i.test(f.base_url.trim())) out.base_url = 'errUrl'
  if (!f.model.trim()) out.model = 'errModel'
  if (f.provider === 'anthropic' && !keyInput.trim() && (!keySet || clearKey)) out.api_key = 'errKey'
  for (const k of ['timeout', 'max_tokens'] as const) {
    const v = f[k], [lo, hi] = LIMITS[k]
    if (!Number.isInteger(v) || v < lo || v > hi) out[k] = 'errRange'
  }
  return out
}

export interface AiPayload {
  provider?: string
  base_url?: string
  model?: string
  model_extract?: string
  model_merge?: string
  timeout?: number
  max_tokens?: number
  api_key?: string
  clear_api_key: boolean
}

/** PUT /ai/settings 的内容：只提交改动过且不是环境变量来源的项；API Key 只在输入了新值时提交。 */
export function buildPayload(orig: AiSettings, f: AiForm, keyInput: string, clearKey: boolean): AiPayload {
  const out: AiPayload = { clear_api_key: false }
  const base = formFrom(orig)
  for (const k of FIELDS) {
    if (isEnv(orig.sources, k)) continue
    const v = typeof f[k] === 'string' ? (f[k] as string).trim() : f[k]
    if (v !== base[k]) (out as unknown as Record<string, unknown>)[k] = v
  }
  if (!isEnv(orig.sources, 'api_key')) {
    if (keyInput.trim()) out.api_key = keyInput.trim()
    else if (clearKey && orig.api_key_set) out.clear_api_key = true
  }
  return out
}

export function payloadIsEmpty(p: AiPayload): boolean {
  return Object.keys(p).filter((k) => k !== 'clear_api_key').length === 0 && !p.clear_api_key
}

/** 演示后端恢复为未配置时用的内容。 */
export const RESET_PAYLOAD: AiPayload = { provider: '', clear_api_key: true }

export interface TaskUsage { task: string; calls: number; ok: number; errors: number; tokensIn: number; tokensOut: number }

/** 按任务汇总调用记录（只算 since 之后的记录；since 为空时全部）。 */
export function usageByTask(calls: AiCall[], since?: Date): TaskUsage[] {
  const m = new Map<string, TaskUsage>()
  for (const c of calls) {
    if (since && !(parseIso(c.created_at) >= since.getTime())) continue
    const u = m.get(c.task) ?? { task: c.task, calls: 0, ok: 0, errors: 0, tokensIn: 0, tokensOut: 0 }
    u.calls += 1
    if (c.status === 'ok') u.ok += 1
    else u.errors += 1
    u.tokensIn += c.tokens_in ?? 0
    u.tokensOut += c.tokens_out ?? 0
    m.set(c.task, u)
  }
  return [...m.values()].sort((a, b) => b.tokensIn + b.tokensOut - (a.tokensIn + a.tokensOut))
}

export function monthStart(now = new Date()): Date {
  return new Date(now.getFullYear(), now.getMonth(), 1)
}

export function fmtTokens(v: number): string {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(2)}M`
  if (v >= 10_000) return `${(v / 1000).toFixed(1)}k`
  return v.toLocaleString('en-US')
}

/** 各任务实际使用的模型：任务模型留空时用默认模型。 */
export function effectiveModel(f: AiForm, task: 'extract' | 'merge'): string {
  return (task === 'extract' ? f.model_extract : f.model_merge).trim() || f.model.trim()
}
