/** M4 页面共用的小工具：设备厂商标记、文件名、文本块截取。 */

/** 平台族 / 厂商 / Profile → 设备标记（hw 华为、cs Cisco）。 */
export function vendorMark(s: string | null | undefined): 'hw' | 'cs' | '' {
  const v = (s ?? '').toLowerCase()
  if (v.startsWith('huawei')) return 'hw'
  if (v.startsWith('cisco')) return 'cs'
  return ''
}

/** 文件名里不能出现的字符换成下划线。 */
export function safeName(s: string | null | undefined, fallback = 'config'): string {
  const t = (s ?? '').trim().replace(/[^\w.@-]+/g, '_')
  return t || fallback
}

/** 今天的日期（yyyymmdd），用于下载文件名。 */
export function stamp(d = new Date()): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}`
}

/** 文本 → 行（统一换行符，去掉末尾空行）。 */
export function lines(text: string | null | undefined): string[] {
  if (!text) return []
  return text.replace(/\r\n?/g, '\n').replace(/\n+$/, '').split('\n')
}

const INDENT = /^\s+/

/**
 * 配置中某个块：从“开头是 head 的那一行”起，连同其后缩进的行（华为 # 与 Cisco ! 分隔行之前）。
 * 返回 1 起的行号与文本；找不到时为空。用于在详情里显示接口等对象的原文。
 */
export function blockOf(all: string[], head: string): { no: number; text: string }[] {
  const h = head.trim().toLowerCase()
  const i = all.findIndex((l) => l.trim().toLowerCase() === h)
  if (i < 0) return []
  const out = [{ no: i + 1, text: all[i] }]
  for (let j = i + 1; j < all.length; j++) {
    const l = all[j]
    if (!INDENT.test(l) || /^\s*[#!]\s*$/.test(l)) break
    out.push({ no: j + 1, text: l })
  }
  return out
}

/** 行号列表 → 带上下文的片段（每段前后各 ctx 行，重叠的段合并；段之间用 null 分隔）。 */
export function snippet(all: string[], nos: number[], ctx = 1): ({ no: number; text: string } | null)[] {
  const want = [...new Set(nos.filter((n) => n >= 1 && n <= all.length))].sort((a, b) => a - b)
  const out: ({ no: number; text: string } | null)[] = []
  let last = 0
  for (const n of want) {
    const a = Math.max(1, n - ctx)
    const b = Math.min(all.length, n + ctx)
    const from = Math.max(a, last + 1)
    if (last && from > last + 1) out.push(null)
    for (let k = from; k <= b; k++) out.push({ no: k, text: all[k - 1] })
    last = Math.max(last, b)
  }
  return out
}
