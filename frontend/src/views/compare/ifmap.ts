/** 跨厂商接口映射表：A 侧接口 → B 侧接口，作为 interface_map 传给 POST /compare；CSV 导入导出。 */

export type MapHow = 'same' | 'manual' | 'none'
export interface MapRow { a: string; b: string; how: MapHow }

/** 粗略的同名判断：去空白、不分大小写（后端还会做缩写展开，这里只用来预填）。 */
export function sameName(x: string, y: string): boolean {
  return x.replace(/\s+/g, '').toLowerCase() === y.replace(/\s+/g, '').toLowerCase()
}

/** 只列主接口：子接口（带 .）由后端按父接口映射。 */
export function mainInterfaces(names: string[]): string[] {
  const out = [...new Set(names.filter((n) => n && !n.includes('.')))]
  return out.sort((p, q) => p.localeCompare(q, undefined, { numeric: true }))
}

/** 初始表：A 的每个主接口一行，B 有同名接口时预填为“同名”，否则未映射。 */
export function initialRows(aIfs: string[], bIfs: string[]): MapRow[] {
  return mainInterfaces(aIfs).map((a) => {
    const b = bIfs.find((x) => sameName(a, x))
    return b ? { a, b, how: 'same' } : { a, b: '', how: 'none' }
  })
}

/** 更新一行的 B 侧选择。 */
export function setRow(rows: MapRow[], a: string, b: string): MapRow[] {
  return rows.map((r) => (r.a === a ? { a, b, how: !b ? 'none' : sameName(a, b) ? 'same' : 'manual' } : r))
}

/** 传给后端的映射：完全同名的不必传（后端本来就按名字配对），未映射的不传；只差大小写的要传（Loopback0 → LoopBack0，REQ-055-35）。 */
export function toInterfaceMap(rows: MapRow[]): Record<string, string> {
  const m: Record<string, string> = {}
  for (const r of rows) if (r.a && r.b && (r.how === 'manual' || (r.how === 'same' && r.a.trim() !== r.b.trim()))) m[r.a] = r.b
  return m
}

/**
 * 解析映射文件（CSV 或与 CLI 相同的两列文本）：每行两列，逗号、分号、制表符、= 或空白分隔；
 * # 开头为注释；第一行是表头（a,b / A,B / interface_a,…）时跳过；字段可加双引号。
 */
export function parseMapCsv(text: string): { pairs: [string, string][]; bad: number[] } {
  const pairs: [string, string][] = []
  const bad: number[] = []
  const lines = text.replace(/^﻿/, '').split(/\r?\n/)
  lines.forEach((raw, i) => {
    const line = raw.trim()
    if (!line || line.startsWith('#')) return
    const cells = splitCells(line)
    if (cells.length < 2 || !cells[0] || !cells[1]) {
      bad.push(i + 1)
      return
    }
    if (pairs.length === 0 && /^(a|b|interface[_ ]?a|a[_ ]?interface|from|source)$/i.test(cells[0])) return
    pairs.push([cells[0], cells[1]])
  })
  return { pairs, bad }
}

function splitCells(line: string): string[] {
  if (line.includes('"')) {
    const out: string[] = []
    let cur = ''
    let q = false
    for (let i = 0; i < line.length; i++) {
      const ch = line[i]
      if (q) {
        if (ch === '"' && line[i + 1] === '"') {
          cur += '"'
          i++
        } else if (ch === '"') q = false
        else cur += ch
      } else if (ch === '"') q = true
      else if (ch === ',' || ch === ';' || ch === '\t') {
        out.push(cur.trim())
        cur = ''
      } else cur += ch
    }
    out.push(cur.trim())
    return out.filter((c, i) => c || i < 2)
  }
  const sep = /[,;\t=]/.test(line) ? /\s*[,;\t=]\s*/ : /\s+/
  return line.split(sep).map((c) => c.trim())
}

/** 把导入的映射合并进表：已有行更新 B 侧，表里没有的 A 接口追加为手动行。 */
export function mergePairs(rows: MapRow[], pairs: [string, string][]): MapRow[] {
  let out = rows.slice()
  for (const [a, b] of pairs) {
    const hit = out.find((r) => sameName(r.a, a))
    if (hit) out = setRow(out, hit.a, b)
    else out.push({ a, b, how: sameName(a, b) ? 'same' : 'manual' })
  }
  return out
}

/** 导出表格的行（含表头）；未映射的也导出，便于离线填写。 */
export function mapCsvRows(rows: MapRow[]): string[][] {
  return [['a', 'b'], ...rows.map((r) => [r.a, r.b])]
}
