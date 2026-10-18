/**
 * 显示风格（REQ-026）：同一张配置图按华为或 Cisco 的叫法与命令写法显示。
 * 与后端 src/lmesh/core/terms.py 的 Terms.label / name / attr、split_node_id、describe 逐条对应，结果必须一致
 * （测试用例取自 tests/unit/test_terms.py）。只影响显示，不影响解析、对比、检查的结果。
 */

export const STYLES = ['huawei', 'cisco'] as const
export type Style = (typeof STYLES)[number]

export type I18nText = Record<string, string>

export interface ObjectStyle {
  name?: I18nText
  label?: string[]
  values?: Record<string, Record<string, string>>
}

/** GET /api/v1/kb/terms 的返回。 */
export interface TermsData {
  default: string
  styles: Record<string, I18nText>
  objects: Record<string, Partial<Record<string, ObjectStyle>>>
  attrs: Record<string, Partial<Record<string, string>>>
}

/** Schema 里与显示有关的部分：节点编号、单键对象的键名、语义。 */
export interface SchemaIndex {
  ids: Set<string>
  keyNames: Map<string, string[]>
  semantic: Map<string, I18nText | null>
}

export interface SchemaNodeLite {
  id: string
  type: string
  key?: string[]
  semantic?: I18nText | null
}

export function schemaIndex(domains: { nodes: SchemaNodeLite[] }[]): SchemaIndex {
  const idx: SchemaIndex = { ids: new Set(), keyNames: new Map(), semantic: new Map() }
  for (const d of domains) {
    for (const n of d.nodes) {
      idx.ids.add(n.id)
      idx.semantic.set(n.id, n.semantic ?? null)
      if (n.type === 'object' && n.key?.length === 1) idx.keyNames.set(n.id, [...n.key])
    }
  }
  return idx
}

export const EMPTY_TERMS: TermsData = { default: 'huawei', styles: {}, objects: {}, attrs: {} }
const FALLBACK_KEYS = ['name', 'id', 'address', 'asn', 'seq', 'value', 'prefix', 'interface', 'protocol', 'peer']
const FIELD = /\{([\w-]+)\}/g

export function toStyle(style: string | null | undefined): Style {
  return (STYLES as readonly string[]).includes(style ?? '') ? (style as Style) : 'huawei'
}

/** Python 的 str()：布尔与空值写法与后端一致，列表 / 字典按 JSON。 */
function pyStr(v: unknown): string {
  if (v === null || v === undefined) return 'None'
  if (v === true) return 'True'
  if (v === false) return 'False'
  if (typeof v === 'string') return v
  if (typeof v === 'number') return String(v)
  return JSON.stringify(v)
}

/** Python 的真值判断（"" / 0 / False / None / 空列表 / 空字典为假）。 */
function truthy(v: unknown): boolean {
  if (v === null || v === undefined || v === '' || v === 0 || v === false) return false
  if (Array.isArray(v)) return v.length > 0
  if (typeof v === 'object') return Object.keys(v as object).length > 0
  return true
}

export class Terms {
  constructor(
    public data: TermsData = EMPTY_TERMS,
    public schema: SchemaIndex = { ids: new Set(), keyNames: new Map(), semantic: new Map() },
  ) {}

  get defaultStyle(): Style {
    return toStyle(this.data.default)
  }

  private spec(schema: string, style: string): ObjectStyle {
    return this.data.objects[schema]?.[toStyle(style)] ?? {}
  }

  /** 对象类型的叫法；没有登记时用 Schema 的 semantic，再没有用编号。 */
  name(schema: string, style: string, lang = 'zh-CN'): string {
    const names = this.spec(schema, style).name ?? {}
    if (Object.keys(names).length) return String(names[lang] || names.en || Object.values(names)[0])
    const sem = this.schema.semantic.get(schema)
    if (sem && Object.keys(sem).length) return String(sem[lang] || sem.en || Object.values(sem)[0])
    return schema
  }

  private keyDict(key: unknown, schema: string): Record<string, unknown> {
    if (key !== null && typeof key === 'object' && !Array.isArray(key)) return { ...(key as Record<string, unknown>) }
    if (key === null || key === undefined) return {}
    const out: Record<string, unknown> = { _: key }
    for (const n of this.schema.keyNames.get(schema) ?? FALLBACK_KEYS) out[n] = key
    return out
  }

  /** 对象节点在该风格下的命令写法，例如 vrf.instance + "RAN" → ip vpn-instance RAN / vrf definition RAN。 */
  label(schema: string, key: unknown, style: string): string {
    const spec = this.spec(schema, style)
    const keys = this.keyDict(key, schema)
    const values = spec.values ?? {}
    const shown: Record<string, string> = {}
    for (const [k, v] of Object.entries(keys)) {
      const map = values[k] ?? {}
      const s = pyStr(v)
      shown[k] = Object.prototype.hasOwnProperty.call(map, s) ? pyStr(map[s]) : s
    }
    for (const cand of spec.label ?? []) {
      const c = String(cand)
      const at = c.indexOf(' ? ')
      const tpl = at >= 0 ? c.slice(0, at) : c
      const need = at >= 0 ? c.slice(at + 3).split(',').map((r) => r.trim()).filter(Boolean) : []
      if (need.some((r) => !(truthy(keys[r]) ? pyStr(keys[r]) : '').trim())) continue
      return tpl.replace(FIELD, (_m, f: string) => shown[f] ?? '').replace(/\s+/g, ' ').trim()
    }
    const text = Object.values(keys).map(pyStr).filter((s) => s.trim()).join(' ')
    const leaf = schema.slice(schema.lastIndexOf('.') + 1)
    return `${leaf} ${text}`.trim()
  }

  /** 属性在该风格下的命令关键字；没有登记时返回 null（界面用 Schema 的名称）。 */
  attr(schema: string, style: string): string | null {
    const v = this.data.attrs[schema]?.[toStyle(style)]
    return v ? String(v) : null
  }

  /** Schema 节点在该风格下的命令写法模板（Schema 视图用）：对象给出 label 候选（去掉条件），属性给出关键字。 */
  template(schema: string, style: string): string | null {
    const labels = this.spec(schema, style).label
    if (labels?.length) return [...new Set(labels.map((c) => String(c).split(' ? ')[0]))].join(' | ')
    return this.attr(schema, style)
  }

  /** 规范编号按显示风格拆成命令路径的各层；认不出的层原样保留。 */
  describeParts(nodeId: string, style: string): string[] {
    const out: string[] = []
    let parent: string | null = null
    for (const [short, rawKey] of splitNodeId(nodeId)) {
      if (short === 'raw' || short === 'ext' || short === 'unknown') {
        out.push(`${short} ${rawKey ?? ''}`.trim())
        continue
      }
      const schema: string = this.schema.ids.has(short)
        ? short
        : parent && this.schema.ids.has(`${parent}.${short}`)
          ? `${parent}.${short}`
          : short
      if (rawKey !== null) out.push(this.label(schema, parseKey(rawKey), style))
      else out.push(this.attr(schema, style) || short)
      parent = schema
    }
    return out.filter(Boolean)
  }

  describe(nodeId: string, style: string, sep = ' › '): string {
    return this.describeParts(nodeId, style).join(sep)
  }
}

/**
 * 把图的节点编号按层拆开（方括号里的 / 不拆）：
 * interface[GigabitEthernet0/2/1]/ospf[_]/cost → [["interface", "GigabitEthernet0/2/1"], ["ospf", "_"], ["cost", null]]
 */
export function splitNodeId(nodeId: string): [string, string | null][] {
  const parts: [string, string | null][] = []
  let depth = 0
  let buf = ''
  for (const ch of nodeId) {
    if (ch === '[') depth++
    else if (ch === ']') depth--
    if (ch === '/' && depth === 0) {
      parts.push(seg(buf))
      buf = ''
    } else buf += ch
  }
  if (buf) parts.push(seg(buf))
  return parts
}

function seg(text: string): [string, string | null] {
  if (text.endsWith(']') && text.includes('[')) {
    const i = text.indexOf('[')
    return [text.slice(0, i), text.slice(i + 1, -1)]
  }
  return [text, null]
}

export function parseKey(raw: string | null): unknown {
  if (raw === null) return null
  const parts = raw.split(',')
  if (raw.includes('=') && parts.every((p) => p.includes('='))) {
    const out: Record<string, string> = {}
    for (const p of parts) {
      const i = p.indexOf('=')
      out[p.slice(0, i)] = p.slice(i + 1)
    }
    return out
  }
  return raw
}
