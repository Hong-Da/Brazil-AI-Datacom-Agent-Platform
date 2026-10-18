/** 未识别行页的纯逻辑：归一化写法的占位符拆分、状态、筛选。 */

export interface UnknownPattern { view: string; pattern: string; count: number; example: string }
/** 送审状态：未送审的模式不在 states 里。 */
export type PatState = 'new' | 'pending' | 'approved' | 'rejected'

export function stateOf(states: Record<string, string>, pattern: string): PatState {
  const s = states[pattern]
  return s === 'pending' || s === 'approved' || s === 'rejected' ? s : 'new'
}

/** 归一化写法里的占位符（<n>、<ip>）单独标出，便于高亮。 */
export function patternParts(p: string): { text: string; ph: boolean }[] {
  const out: { text: string; ph: boolean }[] = []
  const re = /<(?:n|ip)>/g
  let last = 0
  for (let m = re.exec(p); m; m = re.exec(p)) {
    if (m.index > last) out.push({ text: p.slice(last, m.index), ph: false })
    out.push({ text: m[0], ph: true })
    last = m.index + m[0].length
  }
  if (last < p.length) out.push({ text: p.slice(last), ph: false })
  return out
}

export interface PatFilter { q: string; view: string; state: '' | PatState }

export function patKey(p: UnknownPattern): string {
  return `${p.view}\u0000${p.pattern}`
}

export function filterPatterns(list: UnknownPattern[], states: Record<string, string>, f: PatFilter): UnknownPattern[] {
  const q = f.q.trim().toLowerCase()
  return list
    .filter((p) => {
      if (q && !`${p.pattern}\n${p.example}`.toLowerCase().includes(q)) return false
      if (f.view && p.view !== f.view) return false
      if (f.state && stateOf(states, p.pattern) !== f.state) return false
      return true
    })
    .sort((a, b) => b.count - a.count)
}

export function views(list: UnknownPattern[]): string[] {
  return [...new Set(list.map((p) => p.view))].sort()
}

/** 选中的行 → 要送审的模式（去重，跳过已在审核中的）。 */
export function patternsToSend(list: UnknownPattern[], checked: Set<string>, states: Record<string, string>): string[] {
  const out = new Set<string>()
  for (const p of list) if (checked.has(patKey(p)) && stateOf(states, p.pattern) !== 'pending') out.add(p.pattern)
  return [...out]
}
