/** 对比对象与选项：URL 参数 ⇄ 页面状态，生成 POST /compare 的请求体，报告文件名。 */

export type Mode = 'devices' | 'versions' | 'paste'

export interface SideSel {
  device: number | null
  /** null = 设备的最新版本 */
  version: number | null
  text: string
  profile: string
}

export interface Options {
  domain: string
  includeRaw: boolean
  hideIdentity: boolean
  threshold: number
}

export interface Setup { mode: Mode; a: SideSel; b: SideSel; opts: Options }

export const emptySide = (): SideSel => ({ device: null, version: null, text: '', profile: '' })
export const defaultOptions = (): Options => ({ domain: '', includeRaw: false, hideIdentity: false, threshold: 1 })

type Query = Record<string, string | null | (string | null)[] | undefined>

function q1(q: Query, k: string): string {
  const v = q[k]
  return (Array.isArray(v) ? v[0] : v) ?? ''
}
function num(s: string): number | null {
  if (!/^\d+$/.test(s)) return null
  return Number(s)
}

/**
 * URL 参数：
 * - 两台设备：?a=<设备id>&b=<设备id>，可加 av / bv（版本 id，缺省为最新版本）
 * - 同一设备两个版本：?a=<设备id>&av=<版本id>&bv=<版本id>（不给 b，或 b 与 a 相同）；也可写 mode=versions
 * - 选项：domain=<功能域>、raw=1（包含原文行）、hide=1（隐藏设备身份差异）、th=0.9（改名识别阈值）
 * 返回 null 表示没有可用参数；complete 表示两边都已指定，可以直接开始对比。
 */
export function fromQuery(q: Query): { setup: Setup; complete: boolean } | null {
  const a = num(q1(q, 'a'))
  const b = num(q1(q, 'b'))
  const av = num(q1(q, 'av'))
  const bv = num(q1(q, 'bv'))
  const mode = q1(q, 'mode')
  const opts = defaultOptions()
  opts.domain = q1(q, 'domain')
  opts.includeRaw = q1(q, 'raw') === '1'
  opts.hideIdentity = q1(q, 'hide') === '1'
  const th = Number(q1(q, 'th'))
  if (th > 0 && th <= 1) opts.threshold = th
  if (a === null) return mode === 'paste' ? { setup: { mode: 'paste', a: emptySide(), b: emptySide(), opts }, complete: false } : null
  const versions = mode === 'versions' || (mode !== 'devices' && (b === null || b === a) && (av !== null || bv !== null))
  if (versions) {
    return {
      setup: { mode: 'versions', a: { ...emptySide(), device: a, version: av }, b: { ...emptySide(), device: a, version: bv }, opts },
      complete: av !== null && bv !== null,
    }
  }
  return {
    setup: { mode: 'devices', a: { ...emptySide(), device: a, version: av }, b: { ...emptySide(), device: b, version: bv }, opts },
    complete: b !== null,
  }
}

/** 页面状态 → URL 参数（粘贴模式只记 mode，文本不进 URL）。 */
export function toQuery(s: Setup): Record<string, string> {
  const q: Record<string, string> = {}
  if (s.mode === 'paste') q.mode = 'paste'
  else {
    if (s.a.device !== null) q.a = String(s.a.device)
    if (s.mode === 'devices' && s.b.device !== null) q.b = String(s.b.device)
    if (s.mode === 'versions') q.mode = 'versions'
    if (s.a.version !== null) q.av = String(s.a.version)
    if (s.b.version !== null) q.bv = String(s.b.version)
  }
  if (s.opts.domain) q.domain = s.opts.domain
  if (s.opts.includeRaw) q.raw = '1'
  if (s.opts.hideIdentity) q.hide = '1'
  if (s.opts.threshold !== 1) q.th = String(s.opts.threshold)
  return q
}

/** 两边是否都已选好。 */
export function ready(s: Setup): boolean {
  if (s.mode === 'paste') return !!s.a.text.trim() && !!s.b.text.trim()
  if (s.mode === 'versions') return s.a.device !== null && s.a.version !== null && s.b.version !== null && s.a.version !== s.b.version
  return s.a.device !== null && s.b.device !== null
}

function sideBody(s: Setup, k: 'a' | 'b'): Record<string, unknown> {
  const side = s[k]
  if (s.mode === 'paste') return side.profile ? { text: side.text, profile: side.profile } : { text: side.text }
  const device = s.mode === 'versions' ? s.a.device : side.device
  return side.version !== null ? { device_id: device, version_id: side.version } : { device_id: device }
}

/** POST /compare 的请求体（报告导出复用同一个）。 */
export function compareBody(s: Setup, interfaceMap: Record<string, string> = {}): Record<string, unknown> {
  const body: Record<string, unknown> = {
    a: sideBody(s, 'a'),
    b: sideBody(s, 'b'),
    include_raw: s.opts.includeRaw,
    rename_threshold: s.opts.threshold,
    hide_identity: s.opts.hideIdentity,
  }
  if (s.opts.domain) body.domain = s.opts.domain
  if (Object.keys(interfaceMap).length) body.interface_map = interfaceMap
  return body
}

/** 交换 A 与 B。 */
export function swapSides(s: Setup): Setup {
  return { ...s, a: { ...s.b }, b: { ...s.a } }
}

/** 从 Content-Disposition 取文件名（支持 filename*=UTF-8''…）。 */
export function dispositionName(h: string | null): string {
  if (!h) return ''
  const star = /filename\*\s*=\s*([^']*)''([^;]+)/i.exec(h)
  if (star) {
    try { return decodeURIComponent(star[2].trim().replace(/^"|"$/g, '')) } catch { /* 回退到 filename= */ }
  }
  const m = /filename\s*=\s*("([^"]*)"|[^;]+)/i.exec(h)
  return m ? (m[2] ?? m[1]).trim() : ''
}

/** 后端没给文件名时的默认名：compare-<A>-<B>.<lang>.<ext>（与后端约定一致）。 */
export function reportName(a: string, b: string, lang: string, format: string): string {
  const clean = (x: string) => x.replace(/[\\/:*?"<>|\s]+/g, '_') || 'x'
  return `compare-${clean(a)}-${clean(b)}.${lang}.${format}`
}
