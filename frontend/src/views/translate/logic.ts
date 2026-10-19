/** 配置翻译页的纯逻辑：告警分组、节点改名、两侧行联动、未翻译原文附注、CSV 与报告。 */
import { msg } from '@/views/m3/texts'
import type { GraphNodeLite, Group, Level, OutLine, TranslateResult, TrItem, Warn } from './types'
import { GROUPS } from './types'

// ---------------- 告警 ----------------

const DEFAULT_KINDS = new Set(['default_differs', 'default_unknown', 'explicit_equals_default'])
const RAW_KINDS = new Set(['ext', 'raw', 'unknown', 'negated'])

export function groupOf(it: TrItem, from: Warn['from']): Group {
  if (from === 'defaults' || DEFAULT_KINDS.has(it.kind)) return 'default'
  if (from === 'unsupported') return RAW_KINDS.has(it.kind) ? 'raw' : 'unsup'
  return 'infer'
}

function levelOf(it: TrItem, from: Warn['from']): Level {
  const l = it.params?.level
  if (l === 'error' || l === 'warning' || l === 'info') return l
  if (from === 'defaults') return 'info'
  if (from === 'unsupported') return RAW_KINDS.has(it.kind) ? 'info' : 'warning'
  return 'warning'
}

/** 三个列表合成一张告警表：按分组排序，编号 W1、W2…（同一结果中稳定）。 */
export function buildWarns(r: Pick<TranslateResult, 'warnings' | 'unsupported' | 'defaults'>): Warn[] {
  const all: Omit<Warn, 'id'>[] = []
  for (const from of ['warnings', 'unsupported', 'defaults'] as const) {
    for (const item of r[from] ?? []) all.push({ from, item, group: groupOf(item, from), level: levelOf(item, from) })
  }
  all.sort((a, b) => GROUPS.indexOf(a.group) - GROUPS.indexOf(b.group))
  return all.map((w, i) => ({ ...w, id: `W${i + 1}` }))
}

export function groupCounts(ws: Warn[]): Record<Group, number> {
  const c: Record<Group, number> = { default: 0, unsup: 0, raw: 0, infer: 0 }
  for (const w of ws) c[w.group]++
  return c
}

/** 告警说明（当前语言）：文案键 + 参数。未翻译原文的 text 参数过长时截断。 */
export function warnText(w: Warn, lang: string): string {
  return msg(w.item.key, w.item.params ?? {}, lang)
}

/** 校验发现的意外差异（verify_diff / verify_unknown / verify_failed）。 */
export const isVerifyItem = (w: Warn): boolean => w.item.kind.startsWith('verify_')

// ---------------- 接口改名（源图节点编号 ↔ 译文节点编号） ----------------

function escapeRe(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/**
 * 按接口映射表改写节点编号中的接口名：`[GE0/0/1]`、`[GE0/0/1.100]` 与键值 `=GE0/0/1` 都换。
 * reverse 为 true 时把目标名换回源名。映射表的键按原样比较（不分大小写）。
 */
export function renameNode(id: string, map: Record<string, string>, reverse = false): string {
  let out = id
  for (const [a0, b0] of Object.entries(map)) {
    const [a, b] = reverse ? [b0, a0] : [a0, b0]
    if (!a || !b) continue
    const re = new RegExp(`([\\[=,])${escapeRe(a)}(?=[\\].,/])`, 'gi')
    out = out.replace(re, (_m, p: string) => p + b)
  }
  return out
}

// ---------------- 行联动 ----------------

/** 译文行：节点编号 → 行下标（0 起）。 */
export function outIndex(lines: { nodes: string[] }[]): Map<string, number[]> {
  const m = new Map<string, number[]>()
  lines.forEach((l, i) => {
    for (const n of l.nodes ?? []) {
      const a = m.get(n)
      if (a) a.push(i)
      else m.set(n, [i])
    }
  })
  return m
}

/** 源图：行号 → 节点、节点 → 行号（只取有行号的节点）。 */
export function srcIndex(nodes: GraphNodeLite[]): { lineNodes: Map<number, string[]>; nodeLines: Map<string, number[]> } {
  const lineNodes = new Map<number, string[]>()
  const nodeLines = new Map<string, number[]>()
  for (const n of nodes) {
    const ls = n.lines ?? []
    if (!ls.length || n.kind === 'device') continue
    nodeLines.set(n.id, ls)
    for (const l of ls) {
      const a = lineNodes.get(l)
      if (a) a.push(n.id)
      else lineNodes.set(l, [n.id])
    }
  }
  return { lineNodes, nodeLines }
}

/** 告警在译文中的行（下标）：节点写进了哪一行。 */
export function warnDst(w: Warn, idx: Map<string, number[]>, map: Record<string, string>): number[] {
  const n = w.item.node
  if (!n) return []
  return idx.get(renameNode(n, map)) ?? idx.get(n) ?? []
}

export interface Link { warn?: string; src: number[]; dst: number[] }

/**
 * 点源配置第 lineNo 行：先找说明这一行的告警（默认值类的告警说的是译文，不从源行选中），
 * 再按节点找译文中写出它的行。
 */
export function linkFromSrc(
  lineNo: number, warns: Warn[], dstOf: (w: Warn) => number[],
  lineNodes: Map<number, string[]>, idx: Map<string, number[]>, map: Record<string, string>,
): Link {
  const w = warns.find((x) => x.group !== 'default' && x.item.lines.includes(lineNo))
  if (w) return { warn: w.id, src: w.item.lines, dst: dstOf(w) }
  const dst = new Set<number>()
  for (const n of lineNodes.get(lineNo) ?? []) for (const i of idx.get(renameNode(n, map)) ?? []) dst.add(i)
  return { src: [lineNo], dst: [...dst].sort((a, b) => a - b) }
}

/** 点译文第 i 行（下标）：先找告警，再按节点找源配置行。 */
export function linkFromDst(
  i: number, out: { nodes: string[]; warn?: string }[], warns: Warn[], dstOf: (w: Warn) => number[],
  nodeLines: Map<string, number[]>, map: Record<string, string>,
): Link {
  const line = out[i]
  if (!line) return { src: [], dst: [] }
  if (line.warn) {
    const w = warns.find((x) => x.id === line.warn)
    if (w) return { warn: w.id, src: w.item.lines, dst: [i] }
  }
  const w = warns.find((x) => dstOf(x).includes(i))
  if (w) return { warn: w.id, src: w.item.lines, dst: dstOf(w) }
  const src = new Set<number>()
  for (const n of line.nodes ?? []) for (const l of nodeLines.get(renameNode(n, map, true)) ?? nodeLines.get(n) ?? []) src.add(l)
  return { src: [...src].sort((a, b) => a - b), dst: [i] }
}

// ---------------- 译文附注 ----------------

export interface ShownLine extends OutLine { warn?: string }

/**
 * 未翻译的原文以注释附在译文末尾（结尾的 return / end 之前）。华为、Cisco 都把 “!” 开头的行当注释，重新解析不影响图。
 * 返回新的行表（附注行的 warn 指向对应告警）。
 */
export function appendRaw(lines: OutLine[], warns: Warn[], header: string): ShownLine[] {
  const raws = warns.filter((w) => w.group === 'raw')
  if (!raws.length) return lines
  const last = lines[lines.length - 1]
  const hasEnd = !!last && /^(return|end)\s*$/.test(last.text)
  const body = hasEnd ? lines.slice(0, -1) : lines.slice()
  const extra: ShownLine[] = [{ no: 0, text: `! ${header}`, kind: 'comment', origin: 'note', nodes: [], card: null }]
  for (const w of raws) {
    const text = String(w.item.params?.text ?? '')
    extra.push({ no: 0, text: `!   ${text}`, kind: 'comment', origin: 'note', nodes: [], card: null, warn: w.id })
  }
  const out: ShownLine[] = [...body, ...extra, ...(hasEnd ? [last] : [])]
  return out.map((l, k) => ({ ...l, no: k + 1 }))
}

export function linesText(lines: { text: string }[]): string {
  return lines.map((l) => l.text).join('\n') + '\n'
}

// ---------------- 下载 ----------------

export function warnCsvRows(ws: Warn[], dstOf: (w: Warn) => number[], lang: string): (string | number)[][] {
  return [
    ['id', 'group', 'kind', 'level', 'node', 'schema', 'source_lines', 'output_lines', 'message'],
    ...ws.map((w) => [
      w.id, w.group, w.item.kind, w.level, w.item.node ?? '', w.item.schema ?? '',
      w.item.lines.join(' '), dstOf(w).map((i) => i + 1).join(' '), warnText(w, lang),
    ]),
  ]
}

const GROUP_NAME: Record<'zh-CN' | 'en', Record<Group, string>> = {
  'zh-CN': { default: '默认值', unsup: '目标不支持', raw: '未翻译的原文', infer: '推导值与其他' },
  en: { default: 'Defaults', unsup: 'Not supported on target', raw: 'Untranslated lines', infer: 'Inferred and other' },
}

/** 翻译报告（Markdown，中文或英文）。密码与密钥不出现在结果中（脱敏后的配置）。 */
export function reportMd(r: TranslateResult, ws: Warn[], lang: 'zh-CN' | 'en', when: string): string {
  const zh = lang === 'zh-CN'
  const t = (a: string, b: string) => (zh ? a : b)
  const v = r.verify
  const verify = !v.checked
    ? t('未校验', 'not verified')
    : v.equal
      ? t('一致', 'consistent')
      : t(`差异 ${v.diffs ?? 0} 项，未解释 ${v.unexplained ?? 0} 项`, `${v.diffs ?? 0} differences, ${v.unexplained ?? 0} unexplained`)
  const s = r.stats
  const md = [
    `# ${t('配置翻译报告', 'Configuration translation report')}`,
    '',
    `- ${t('源', 'Source')}: ${r.source.device ?? '-'} (${r.source.profile})`,
    `- ${t('目标 Profile', 'Target Profile')}: ${r.target.profile}`,
    `- ${t('时间', 'Time')}: ${when}`,
    `- ${t('写出节点', 'Nodes written')}: ${s.rendered} / ${s.facts}`,
    `- ${t('翻译后再解析与源对比', 'Output parsed again and compared with the source')}: ${verify}`,
  ]
  const map = Object.entries(r.interface_map ?? {})
  if (map.length) md.push(`- ${t('接口映射', 'Interface map')}: ${map.map(([a, b]) => `${a} → ${b}`).join(', ')}`)
  md.push('', `## ${t('告警', 'Warnings')}`, '', `| ID | ${t('类别', 'Group')} | ${t('级别', 'Level')} | ${t('源行', 'Source lines')} | ${t('说明', 'Summary')} |`, '|---|---|---|---|---|')
  for (const w of ws) {
    md.push(`| ${w.id} | ${GROUP_NAME[lang][w.group]} | ${w.level} | ${w.item.lines.join(' ')} | ${warnText(w, lang).replace(/\|/g, '\\|')} |`)
  }
  if (!ws.length) md.push(`| - | - | - | - | ${t('没有告警', 'No warnings')} |`)
  md.push('', t('> 由透网 LucidMesh 生成；配置与报告都来自脱敏后的数据。', '> Generated by LucidMesh; the config and report come from sanitized data.'), '')
  return md.join('\n')
}

/**
 * 从配置图列出顶层接口对象的名字（interface[X] 的键），用于 Nokia 等不以 `interface X` 开头声明端口的平台
 * （端口、LAG、路由器接口分在 port / lag / router 等上下文里）。
 */
export function interfacesInGraph(nodes: { id: string; kind: string; schema: string | null; key?: unknown }[]): string[] {
  const out = new Set<string>()
  for (const n of nodes) {
    if (n.kind !== 'object' || n.schema !== 'interface' || typeof n.key !== 'string' || !n.key) continue
    if (n.id === `interface[${n.key}]`) out.add(n.key)
  }
  return [...out]
}

/** 从配置文本中列出接口名（`interface X` 行），用于接口映射表。 */
export function interfacesIn(text: string): string[] {
  const out = new Set<string>()
  for (const line of text.split(/\r?\n/)) {
    const m = /^interface\s+(\S+)/i.exec(line)
    if (m) out.add(m[1])
  }
  return [...out]
}
