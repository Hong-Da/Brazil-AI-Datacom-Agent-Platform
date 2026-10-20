/* REQ-042 设备图标的三套图形（移植自 DevelopDocs/ui-preview/REQ-042/assets/icons-*.js，已评审）。
   48×48 网格，currentColor 着色；类名：f 机身浅色填充、t 顶面较深填充、d 细节（16 px 时隐藏）、dash 虚线轮廓。 */

export type IconSetId = 'cyl' | 'geo' | 'line'
export interface IconSet { id: IconSetId; name: Record<'zh-CN' | 'en' | 'pt-BR', string>; glyphs: Record<string, string> }

const cyl: IconSet = {
  id: 'cyl',
  name: { 'zh-CN': 'A 圆柱', en: 'A Cylinder', 'pt-BR': 'A Cilindro' },
  glyphs: {
    core: '<path class="f" d="M7 13v24c0 3.3 7.6 6 17 6s17-2.7 17-6V13"/><path d="M7 25c0 3.3 7.6 6 17 6s17-2.7 17-6"/><ellipse class="t" cx="24" cy="13" rx="17" ry="6"/><path class="d" d="M16.5 10.8l5 1.8M31.5 15.2l-5-1.8M31.5 10.8l-5 1.8M16.5 15.2l5-1.8"/>',
    agg: '<path class="f" d="M7 17v16c0 3.3 7.6 6 17 6s17-2.7 17-6V17"/><ellipse class="t" cx="24" cy="17" rx="17" ry="6"/><path d="M11 29h8M16 26l3 3-3 3M37 29h-8M32 26l-3 3 3 3"/>',
    access: '<path class="f" d="M9 26v10c0 2.8 6.7 5 15 5s15-2.2 15-5V26"/><ellipse class="t" cx="24" cy="26" rx="15" ry="5"/><path d="M24 26V5M18.5 10.5 24 5l5.5 5.5"/>',
    pe: '<path class="f" d="M5 17v16c0 3 7 5.5 15.5 5.5S36 36 36 33V17"/><ellipse class="t" cx="20.5" cy="17" rx="15.5" ry="5.5"/><path d="M15 29h29M39.5 24.5 44 29l-4.5 4.5"/>',
    p: '<path class="f" d="M7 17v16c0 3.3 7.6 6 17 6s17-2.7 17-6V17"/><ellipse class="t" cx="24" cy="17" rx="17" ry="6"/><path d="M3 29h42M7.5 24.5 3 29l4.5 4.5M40.5 24.5 45 29l-4.5 4.5"/>',
    ce: '<path class="f" d="M6 24h36v12a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2z"/><path class="t" d="M6 24l7-8h22l7 8z"/><path d="M14 31h20"/><path class="d" d="M24 16v-6M21 12.5l3-3 3 3"/>',
    peer: '<path class="dash" d="M7 17v16c0 3.3 7.6 6 17 6s17-2.7 17-6V17"/><ellipse class="dash" cx="24" cy="17" rx="17" ry="6"/><path d="M20 25.5a4 4 0 1 1 5.6 3.7c-1 .5-1.6 1.2-1.6 2.3v.8M24 35.5v.01"/>',
    cloud: '<path class="f" d="M13 38h23a9 9 0 0 0 1.4-17.9A13 13 0 0 0 12.6 17.4a10.3 10.3 0 0 0 .4 20.6z"/>',
    plat_atn: '<path class="f" d="M9 20h25v18H9z"/><path class="t" d="M9 20l6-7h25l-6 7z"/><path class="f" d="M34 20l6-7v18l-6 7z"/><path class="d" d="M13 33h.01M17 33h.01M21 33h.01M25 33h5"/>',
    plat_asr920: '<path class="f" d="M4 24h34v8H4z"/><path class="t" d="M4 24l6-6h34l-6 6z"/><path class="f" d="M38 24l6-6v8l-6 6z"/><path class="d" d="M8 28h.01M12 28h.01M16 28h.01M25 28h9"/>',
    plat_7750: '<path class="f" d="M11 9h22v35H11z"/><path class="t" d="M11 9l6-5h22l-6 5z"/><path class="f" d="M33 9l6-5v35l-6 5z"/><path d="M15 16h14M15 23h14M15 30h14"/><circle class="d" cx="22" cy="38" r="2.5"/>',
  },
}

const geo: IconSet = {
  id: 'geo',
  name: { 'zh-CN': 'B 几何徽章', en: 'B Geometric badge', 'pt-BR': 'B Emblema geométrico' },
  glyphs: {
    core: '<path class="f" d="M17 4h14l13 13v14L31 44H17L4 31V17z"/><path d="M24 13v22M13 24h22"/><path class="d" d="M20.5 16.5 24 13l3.5 3.5M20.5 31.5 24 35l3.5-3.5M16.5 20.5 13 24l3.5 3.5M31.5 20.5 35 24l-3.5 3.5"/>',
    agg: '<path class="f" d="M24 3.5 42 14v20L24 44.5 6 34V14z"/><path d="M15 33l9-8 9 8M24 25V13"/><path class="d" d="M19.5 17.5 24 13l4.5 4.5"/>',
    access: '<rect class="f" x="6.5" y="6.5" width="35" height="35" rx="8"/><path d="M24 34V14M17 21l7-7 7 7"/><path class="d" d="M16 35h16"/>',
    pe: '<path class="f" d="M6 8h24l14 16-14 16H6z"/><path d="M12 24h17M23 18l6 6-6 6"/>',
    p: '<circle class="f" cx="24" cy="24" r="19.5"/><path d="M12 24h24M17 19l-5 5 5 5M31 19l5 5-5 5"/>',
    ce: '<path class="f" d="M5 21 24 6l19 15v19.5a2.5 2.5 0 0 1-2.5 2.5h-33A2.5 2.5 0 0 1 5 40.5z"/><rect x="15" y="27" width="18" height="8" rx="1.5"/>',
    peer: '<circle class="dash" cx="24" cy="24" r="19.5"/><path d="M18 18.5a6 6 0 1 1 8.6 5.4c-1.6.8-2.6 2-2.6 3.8V30M24 35.5v.01"/>',
    cloud: '<path class="f" d="M13 38h23a9 9 0 0 0 1.4-17.9A13 13 0 0 0 12.6 17.4a10.3 10.3 0 0 0 .4 20.6z"/>',
    plat_atn: '<rect x="10" y="12" width="28" height="24" rx="3"/><path d="M10 29h28"/><path class="d" d="M15 32.5h.01M20 32.5h.01M25 32.5h.01M29 32.5h4M15 18h8"/>',
    plat_asr920: '<rect x="7" y="18" width="34" height="12" rx="2"/><path d="M7 20.5H3.5v7H7M41 20.5h3.5v7H41"/><path class="d" d="M11 22v4M14 22v4M17 22v4M24 24h.01M28 24h.01M32 24h.01M36 24h.01"/>',
    plat_7750: '<rect x="12" y="4" width="24" height="40" rx="2.5"/><path d="M16 12h16M16 20h16M16 28h16"/><circle class="d" cx="24" cy="37" r="3"/>',
  },
}

const line: IconSet = {
  id: 'line',
  name: { 'zh-CN': 'C 线框', en: 'C Line', 'pt-BR': 'C Traço' },
  glyphs: {
    core: '<circle cx="24" cy="24" r="8.5"/><circle class="d" cx="24" cy="24" r="3"/><path d="M24 15.5V5M19.5 9.5 24 5l4.5 4.5M24 32.5V43M19.5 38.5 24 43l4.5-4.5M15.5 24H5M9.5 19.5 5 24l4.5 4.5M32.5 24H43M38.5 19.5 43 24l-4.5 4.5"/>',
    agg: '<circle cx="24" cy="20" r="7.5"/><path d="M24 12.5V4M19.5 8.5 24 4l4.5 4.5M8 43l10.7-17.3M24 27.5V43M40 43 29.3 25.7"/>',
    access: '<rect x="7" y="25" width="34" height="14" rx="3"/><path d="M24 25V6M18.5 11.5 24 6l5.5 5.5"/><path class="d" d="M13 32h.01M18 32h.01M23 32h.01M30 32h6"/>',
    pe: '<circle cx="18" cy="24" r="9"/><path d="M36 6v36M27 24h17M39.5 19.5 44 24l-4.5 4.5"/><circle class="d" cx="18" cy="24" r="2.5"/>',
    p: '<circle cx="24" cy="24" r="9"/><path d="M4 24h11M33 24h11M8.5 19.5 4 24l4.5 4.5M39.5 19.5 44 24l-4.5 4.5"/><path class="d" d="M19.5 24h9"/>',
    ce: '<path d="M7 22 24 8l17 14v18a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2z"/><rect class="d" x="15" y="27" width="18" height="8" rx="1.5"/>',
    peer: '<circle class="dash" cx="24" cy="24" r="17"/><path d="M19 19.5a5 5 0 1 1 7.2 4.5c-1.4.7-2.2 1.7-2.2 3.2V29M24 34v.01"/>',
    cloud: '<path d="M14.5 37H35a8 8 0 0 0 1.2-15.9A11.5 11.5 0 0 0 14.1 19a9 9 0 0 0 .4 18z"/>',
    plat_atn: '<rect x="10" y="12" width="28" height="24" rx="3"/><path d="M10 29h28"/><path class="d" d="M15 32.5h.01M20 32.5h.01M25 32.5h.01M29 32.5h4M15 18h8"/>',
    plat_asr920: '<rect x="7" y="18" width="34" height="12" rx="2"/><path d="M7 20.5H3.5v7H7M41 20.5h3.5v7H41"/><path class="d" d="M11 22v4M14 22v4M17 22v4M24 24h.01M28 24h.01M32 24h.01M36 24h.01"/>',
    plat_7750: '<rect x="12" y="4" width="24" height="40" rx="2.5"/><path d="M16 12h16M16 20h16M16 28h16"/><circle class="d" cx="24" cy="37" r="3"/>',
  },
}

export const ICON_SETS: Record<IconSetId, IconSet> = { cyl, geo, line }
export const ICON_SET_IDS: IconSetId[] = ['cyl', 'geo', 'line']
