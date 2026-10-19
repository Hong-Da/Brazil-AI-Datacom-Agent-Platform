/**
 * Schema 数据类型与输入项（M6-9）：每种类型显示哪些设置项、哪些类型只有格式说明，以及取值的格式校验。
 * Schema 编辑表单与 Profile 默认值输入共用。
 */

export type TypeField = 'range' | 'choices' | 'key' | 'ordered' | 'ref'
export const TYPE_FIELD_ORDER: TypeField[] = ['range', 'choices', 'key', 'ordered', 'ref']

/** 各类型适用的设置项；不在表中的类型（boolean、flag、string、text 与下面的格式类型）没有额外设置。 */
export const TYPE_FIELDS: Record<string, TypeField[]> = {
  integer: ['range'],
  enum: ['choices'],
  object: ['key', 'ordered'],
  ref: ['ref'],
}

/** 只显示格式说明的类型（文案键 schema-edit.fmt.<type>，示例 schema-edit.fmtEg.<type>）。 */
export const FORMAT_TYPES = ['ipv4', 'mask', 'prefix', 'rd', 'asn', 'community', 'interface'] as const

export function fieldsFor(type: string): TypeField[] {
  return TYPE_FIELDS[type] ?? []
}

export function isFormatType(type: string): boolean {
  return (FORMAT_TYPES as readonly string[]).includes(type)
}

const OCTET = '(25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]?\\d)'
const IPV4 = new RegExp(`^${OCTET}(\\.${OCTET}){3}$`)
const U32 = 4294967295
const U16 = 65535
const WELL_KNOWN_COMMUNITIES = ['internet', 'no-export', 'no-advertise', 'local-as', 'no-export-subconfed', 'none', 'gshut', 'accept-own']

function intIn(s: string, lo: number, hi: number): boolean {
  return /^\d+$/.test(s) && Number(s) >= lo && Number(s) <= hi
}

export function isIpv4(s: string): boolean {
  return IPV4.test(s)
}

/** 掩码：点分十进制，且 1 连续在前。 */
export function isMask(s: string): boolean {
  if (!IPV4.test(s)) return false
  const bits = s.split('.').map((x) => Number(x).toString(2).padStart(8, '0')).join('')
  return /^1*0*$/.test(bits)
}

/** 前缀：IPv4/0–32，或 IPv6/0–128（只做粗略检查）。 */
export function isPrefix(s: string): boolean {
  const m = /^([^/]+)\/(\d{1,3})$/.exec(s)
  if (!m) return false
  if (IPV4.test(m[1]!)) return Number(m[2]) <= 32
  return /^[0-9a-fA-F:]+$/.test(m[1]!) && m[1]!.includes(':') && Number(m[2]) <= 128
}

/** AS 号：1–4294967295，或点分写法 a.b（各 0–65535）。 */
export function isAsn(s: string): boolean {
  if (/^\d+$/.test(s)) return intIn(s, 1, U32)
  const m = /^(\d+)\.(\d+)$/.exec(s)
  return !!m && intIn(m[1]!, 0, U16) && intIn(m[2]!, 0, U16) && s !== '0.0'
}

/** RD：ASN:编号 或 IPv4:编号。 */
export function isRd(s: string): boolean {
  const i = s.lastIndexOf(':')
  if (i <= 0) return false
  const a = s.slice(0, i), n = s.slice(i + 1)
  if (IPV4.test(a)) return intIn(n, 0, U16)
  return (isAsn(a) || a === '0') && intIn(n, 0, U32)
}

/** 团体属性：AA:NN（各 0–65535）、32 位整数或知名团体名。 */
export function isCommunity(s: string): boolean {
  if (WELL_KNOWN_COMMUNITIES.includes(s.toLowerCase())) return true
  if (/^\d+$/.test(s)) return intIn(s, 0, U32)
  const m = /^(\d+):(\d+)$/.exec(s)
  return !!m && intIn(m[1]!, 0, U16) && intIn(m[2]!, 0, U16)
}

/** 接口名：非空、不含空白（system、GigabitEthernet0/0/1、Eth-Trunk10 等都可以）。 */
export function isInterfaceName(s: string): boolean {
  return /^\S+$/.test(s)
}

const CHECKS: Record<string, (s: string) => boolean> = {
  ipv4: isIpv4, mask: isMask, prefix: isPrefix, rd: isRd, asn: isAsn, community: isCommunity, interface: isInterfaceName,
}

/** 按类型检查一个取值的格式；空串不检查。返回 true 表示合格（没有格式要求的类型总是合格）。 */
export function formatOk(type: string, text: string): boolean {
  const s = text.trim()
  if (!s) return true
  const f = CHECKS[type]
  return f ? f(s) : true
}
