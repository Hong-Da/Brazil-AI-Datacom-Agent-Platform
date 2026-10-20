/* REQ-042 设备图标合成器（移植自 DevelopDocs/ui-preview/REQ-042/assets/lmi.js，已评审）：
   图形（sets.ts）+ 厂商标识 + 状态角标 → 一段内联 SVG 字符串，纯函数。
   尺寸分档 72 / 48 / 32 / 24 / 16；描边 non-scaling-stroke，各档按像素给线宽；16 档隐藏细节（.d）、不画厂商标识、
   角标只画一个实心点。角标按优先级 检查 > 一致性 > 过期 > AI 取前 max 个，其余合成“+n”。
   颜色：页面内联时图形 = currentColor，角标与底色取 CSS 变量 --lmi-*（devicon.css）；
   做成图片（cytoscape 的 data URI）时 CSS 变量不生效，传 palette，把颜色与样式写进 SVG 自己的 <style>。 */
import { ICON_SETS, type IconSetId } from './sets'

export type Badge = 'check' | 'cons' | 'stale' | 'ai'
export type VendorCode = 'hw' | 'cs' | 'nk'

interface Size { sw: number; tag: [number, number] | null; br: number; dash: string }
const SZ: Record<number, Size> = {
  72: { sw: 2, tag: [15, 9.5], br: 8.5, dash: '5 4' },
  48: { sw: 1.75, tag: [13, 8.5], br: 7, dash: '4 3' },
  32: { sw: 1.5, tag: [11, 7.5], br: 5.8, dash: '3 2.4' },
  24: { sw: 1.4, tag: null, br: 4.6, dash: '2.4 2' },
  16: { sw: 1.3, tag: null, br: 3.2, dash: '2 1.6' },
}
export const BADGE_ORDER: Badge[] = ['check', 'cons', 'stale', 'ai']
const BADGE: Record<Badge, { fill: string; ink: string; g: string }> = {
  check: { fill: 'var(--lmi-red)', ink: '#fff', g: '<path d="M0-4.3v4.8M0 3.7v.1"/>' },
  cons: { fill: 'var(--lmi-amber)', ink: '#3A2600', g: '<path d="M-4.2-1.6h8.4M-4.2 1.9h8.4M2.2-4.6l-4.4 9.2"/>' },
  stale: { fill: 'var(--lmi-slate)', ink: '#fff', g: '<circle r="4.3"/><path d="M0-2.4V0l1.9 1.4"/>' },
  ai: { fill: 'var(--lmi-violet)', ink: '#fff', g: '<path d="M0-5c.4 2.9 2.1 4.6 5 5-2.9.4-4.6 2.1-5 5-.4-2.9-2.1-4.6-5-5 2.9-.4 4.6-2.1 5-5z" fill="#fff" stroke="none"/>' },
}
export const VENDOR_TAG: Record<VendorCode, string> = { hw: 'HW', cs: 'CS', nk: 'NK' }

/** 做成图片时用的实际颜色（取自当前主题的 CSS 变量）。 */
export interface Palette { ink: string; bg: string; red: string; amber: string; slate: string; violet: string; fill: number; top: number; font: string }

export interface SvgOptions {
  size?: number
  vendor?: VendorCode | '' | null
  badges?: Badge[]
  max?: number
  ghost?: boolean
  title?: string
  cls?: string
  /** 给出时生成独立的 SVG（带 xmlns 与内嵌样式），可做 data URI */
  palette?: Palette
}

export function bucket(s: number): number {
  return s >= 60 ? 72 : s >= 40 ? 48 : s >= 28 ? 32 : s >= 20 ? 24 : 16
}
const f = (n: number) => Math.round(n * 100) / 100
const escAttr = (s: string) => s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
const escText = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

/** 角标按优先级排序、去重（检查 > 一致性 > 过期 > AI）。 */
export function orderBadges(list: Badge[] | undefined): Badge[] {
  return BADGE_ORDER.filter((x) => (list ?? []).includes(x))
}

/** 按尺寸实际显示的角标与“+n”的数量。 */
export function shownBadges(list: Badge[] | undefined, size: number, max = 2): { shown: Badge[]; more: number } {
  const all = orderBadges(list)
  const b = bucket(size)
  const m = b === 16 ? 1 : max
  const shown = all.slice(0, m)
  return { shown, more: b === 16 ? 0 : all.length - shown.length }
}

function embeddedStyle(p: Palette): string {
  return '<style>' +
    `.g{fill:none;stroke:${p.ink};stroke-linecap:round;stroke-linejoin:round}.g *{vector-effect:non-scaling-stroke}` +
    `.g .f{fill:${p.ink};fill-opacity:${p.fill}}.g .t{fill:${p.ink};fill-opacity:${p.top}}.g .dash{stroke-dasharray:var(--lmi-dash)}` +
    '.b16 .g .d{display:none}' +
    `.lmi-vd rect{fill:${p.ink};stroke:${p.bg};stroke-width:1.5}.lmi-vd text{fill:${p.bg};font-family:${p.font};font-weight:700;text-anchor:middle;dominant-baseline:central}` +
    `.lmi-bd>circle{stroke:${p.bg};stroke-width:1.5}.lmi-more rect{fill:${p.bg};stroke:${p.ink};stroke-width:1}` +
    `.lmi-more text{fill:${p.ink};font-family:${p.font};font-weight:700;text-anchor:middle;dominant-baseline:central}` +
    '.ghost .g{opacity:.7}.ghost .g *{stroke-dasharray:3 2.4}.ghost .g .f,.ghost .g .t{fill-opacity:.06}' +
    '</style>'
}

export function svg(set: IconSetId | string, kind: string, o: SvgOptions = {}): string {
  const S = o.size ?? 48
  const b = bucket(S)
  const z = SZ[b]
  const pal = o.palette
  const src = (ICON_SETS[set as IconSetId] ?? ICON_SETS.geo).glyphs[kind] ?? ''
  const k = S / 48
  const cls = `lmi b${b}${o.ghost ? (pal ? ' ghost' : ' lmi-ghost') : ''}${o.cls ? ` ${o.cls}` : ''}`
  let h = `<svg${pal ? ' xmlns="http://www.w3.org/2000/svg"' : ''} class="${cls}" width="${S}" height="${S}" viewBox="0 0 ${S} ${S}" role="img"` +
    (o.title ? ` aria-label="${escAttr(o.title)}"` : ' aria-hidden="true"') + '>' +
    (o.title ? `<title>${escText(o.title)}</title>` : '') +
    (pal ? embeddedStyle(pal) : '') +
    `<g class="g" transform="scale(${f(k)})" stroke-width="${z.sw}" style="--lmi-dash:${z.dash}">${src}</g>`
  if (o.vendor && z.tag) {
    const th = z.tag[0]
    const tw = f(th * 1.62)
    const ty = S - th - 0.5
    h += `<g class="lmi-vd"><rect x="0.5" y="${f(ty)}" width="${tw}" height="${th}" rx="${f(th * 0.22)}"/>` +
      `<text x="${f(0.5 + tw / 2)}" y="${f(ty + th / 2)}" font-size="${z.tag[1]}">${VENDOR_TAG[o.vendor] ?? ''}</text></g>`
  }
  const { shown, more } = shownBadges(o.badges, S, o.max ?? 2)
  if (shown.length) {
    const r = z.br
    let cx = S - r - 0.5
    const cy = r + 0.5
    const colors: Record<string, string> = pal ? { 'var(--lmi-red)': pal.red, 'var(--lmi-amber)': pal.amber, 'var(--lmi-slate)': pal.slate, 'var(--lmi-violet)': pal.violet } : {}
    for (const x of shown) {
      const B = BADGE[x]
      h += `<g class="lmi-bd bd-${x}" transform="translate(${f(cx)} ${f(cy)})"><circle r="${f(r)}" fill="${colors[B.fill] ?? B.fill}"/>` +
        (b === 16 ? '' : `<g transform="scale(${f(r / 8)})" stroke="${B.ink}" stroke-width="1.9" fill="none" stroke-linecap="round" stroke-linejoin="round">${B.g}</g>`) + '</g>'
      cx -= 2 * r + 1.2
    }
    if (more > 0) {
      const pw = r * 1.9
      h += `<g class="lmi-more" transform="translate(${f(cx + r - pw)} ${f(cy - r * 0.78)})"><rect width="${f(pw)}" height="${f(r * 1.56)}" rx="${f(r * 0.5)}"/>` +
        `<text x="${f(pw / 2)}" y="${f(r * 0.78)}" font-size="${f(r * 1.15)}">+${more}</text></g>`
    }
  }
  return h + '</svg>'
}

/** 独立 SVG → data URI（cytoscape 的 background-image）。 */
export function dataUri(s: string): string {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(s)}`
}

/** 读取当前主题的实际颜色（主题切换后重新读）。ink 为图形颜色，默认取 --ink。 */
export function readPalette(inkVar = 'ink', el: Element = document.documentElement): Palette {
  const cs = getComputedStyle(el)
  const v = (n: string, fb: string) => cs.getPropertyValue(`--${n}`).trim() || fb
  const dark = el.getAttribute('data-theme') === 'dark'
  return {
    ink: v(inkVar, dark ? '#D3DFE7' : '#1D3444'),
    bg: v('canvas', dark ? '#101C24' : '#F7FAFC'),
    red: v('lmi-red', dark ? '#E5535C' : '#C9303A'),
    amber: v('lmi-amber', dark ? '#F2B33D' : '#E9A21F'),
    slate: v('lmi-slate', dark ? '#7F95A5' : '#5E7383'),
    violet: v('lmi-violet', dark ? '#A88AF0' : '#7A52C7'),
    fill: Number(v('lmi-fill', dark ? '.16' : '.13')),
    top: Number(v('lmi-top', dark ? '.38' : '.32')),
    font: (v('font-ui', 'sans-serif')).replace(/"/g, "'"),
  }
}
