/** 配置文本面板（components/m3-code.vue）的行模型与小工具。 */

export interface CodePart { s: string; v?: string; cls?: string; title?: string }

export interface CodeLine {
  /** 显示的行号；null 显示为“·”（例如插入的默认行） */
  no: number | null
  text: string
  cls?: string
  /** 分段显示（变量、生成值）；不给时整行显示 text */
  parts?: CodePart[]
  /** 隐藏的默认配置：灰色虚线框 */
  ghost?: boolean
  /** 行尾的小标签（例如“默认”） */
  tag?: string
}

/** 文本 → 行（统一换行符，去掉末尾空行）。 */
export function splitLines(text: string | null | undefined): string[] {
  if (!text) return []
  return text.replace(/\r\n?/g, '\n').replace(/\n+$/, '').split('\n')
}

/** 行号集合 → 连续区间 [[a, b], …]（升序）。 */
export function ranges(idx: number[]): [number, number][] {
  const r: [number, number][] = []
  for (const i of [...new Set(idx)].sort((a, b) => a - b)) {
    const last = r[r.length - 1]
    if (last && i === last[1] + 1) last[1] = i
    else r.push([i, i])
  }
  return r
}
