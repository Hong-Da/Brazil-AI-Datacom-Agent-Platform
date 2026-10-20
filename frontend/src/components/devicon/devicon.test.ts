import { describe, expect, it } from 'vitest'
import { bucket, dataUri, orderBadges, shownBadges, svg, type Palette } from './lmi'
import { ICON_SETS, ICON_SET_IDS } from './sets'
import { annoByDevice, badgesOf, glyphOfRole, pendingOf, peerLinks, platformGlyph, resolveRole, vendorCode, type Annotation } from './logic'

const anno = (target: string, key: string, value: unknown, source: 'user' | 'ai' = 'user', type = 'device'): Annotation =>
  ({ id: 1, target_type: type, target, key, value, source, suggestion_id: null, updated_by: 'a', updated_at: null })

describe('lmi', () => {
  it('three sets share the same glyph names', () => {
    const names = Object.keys(ICON_SETS.geo.glyphs).sort()
    for (const s of ICON_SET_IDS) expect(Object.keys(ICON_SETS[s].glyphs).sort()).toEqual(names)
    expect(names).toEqual(expect.arrayContaining(['core', 'agg', 'access', 'pe', 'p', 'ce', 'peer', 'cloud', 'plat_atn', 'plat_asr920', 'plat_7750']))
  })
  it('size buckets', () => {
    expect([72, 48, 32, 24, 16, 60, 40, 28, 20, 10].map(bucket)).toEqual([72, 48, 32, 24, 16, 72, 48, 32, 24, 16])
  })
  it('badges: priority order, max 2 plus +n, one dot at 16px', () => {
    expect(orderBadges(['ai', 'check', 'stale'])).toEqual(['check', 'stale', 'ai'])
    expect(shownBadges(['ai', 'cons', 'stale', 'check'], 48)).toEqual({ shown: ['check', 'cons'], more: 2 })
    expect(shownBadges(['ai', 'stale'], 16)).toEqual({ shown: ['stale'], more: 0 })
    const h = svg('geo', 'core', { size: 48, badges: ['ai', 'cons', 'stale'] })
    expect(h).toContain('bd-cons')
    expect(h).toContain('bd-stale')
    expect(h).not.toContain('bd-ai')
    expect(h).toContain('>+1<')
  })
  it('vendor tag only from 32px up; ghost class; escapes the title', () => {
    expect(svg('cyl', 'pe', { size: 48, vendor: 'hw' })).toContain('>HW<')
    expect(svg('cyl', 'pe', { size: 24, vendor: 'hw' })).not.toContain('lmi-vd')
    expect(svg('line', 'pe', { ghost: true })).toContain('lmi-ghost')
    const t = svg('geo', 'core', { title: '<a href="x">' })
    expect(t).not.toContain('<a href')
    expect(t).toContain('&lt;a href=&quot;x&quot;&gt;')
  })
  it('unknown set falls back to geo; palette makes a standalone image', () => {
    expect(svg('nope', 'core')).toContain(ICON_SETS.geo.glyphs.core)
    const pal: Palette = { ink: '#111', bg: '#fff', red: '#f00', amber: '#fa0', slate: '#888', violet: '#70f', fill: 0.13, top: 0.32, font: 'sans-serif' }
    const s = svg('geo', 'core', { palette: pal, badges: ['check'] })
    expect(s).toContain('xmlns="http://www.w3.org/2000/svg"')
    expect(s).toContain('stroke:#111')
    expect(s).toContain('fill="#f00"')
    expect(s).not.toContain('var(--lmi-red)')
    expect(dataUri(s)).toMatch(/^data:image\/svg\+xml;charset=utf-8,%3Csvg/)
  })
})

describe('roles', () => {
  it('maps roles to glyphs and platforms to shapes', () => {
    expect(glyphOfRole('aggregation')).toBe('agg')
    expect(glyphOfRole('pe')).toBe('pe')
    expect(platformGlyph('huawei-atn-v800r025', 'huawei-vrp8')).toBe('plat_atn')
    expect(platformGlyph('cisco-iosxe-asr920')).toBe('plat_asr920')
    expect(platformGlyph('nokia-sros-classic')).toBe('plat_7750')
    expect(platformGlyph('huawei')).toBe('plat_atn')
    expect(vendorCode('cisco-iosxe')).toBe('cs')
    expect(vendorCode('', 'huawei-vrp8')).toBe('hw')
    expect(vendorCode('juniper')).toBe('')
  })
  it('manual beats adopted AI beats platform', () => {
    const m = annoByDevice([anno('3', 'role', 'aggregation', 'ai'), anno('4', 'role', 'core', 'user'), anno('9', 'peer', {}, 'ai', 'link')])
    expect(resolveRole(m.get('3'), 'huawei-atn')).toEqual({ glyph: 'agg', role: 'aggregation', source: 'ai' })
    expect(resolveRole(m.get('4'))).toEqual({ glyph: 'core', role: 'core', source: 'user' })
    expect(resolveRole(m.get('5'), 'cisco-iosxe-asr920')).toEqual({ glyph: 'plat_asr920', role: null, source: 'platform' })
    expect(resolveRole({ role: anno('6', 'role', 'firewall') }, 'nokia')).toMatchObject({ source: 'platform', glyph: 'plat_7750' })
    expect(m.has('9')).toBe(false)
  })
  it('collects adopted peers and pending suggestions (rejected ones skipped)', () => {
    const peers = peerLinks([anno('1|x', 'peer', { a: { device_id: 1, name: 'A', interface: 'GE0/1', address: '10.0.0.1' }, b: { device_id: null, name: '', interface: null, address: '10.0.0.2' }, external: false, label: 'AS 65010' }, 'ai', 'link')])
    expect(peers[0]).toMatchObject({ external: true, label: 'AS 65010' })
    const ref = (id: string, device_id: number) => ({ id, found: true, device_id, label: `dev${device_id}` })
    const p = pendingOf([
      { id: 1, category: 'view_hint', kind: 'role', status: 'pending', check_status: 'pass', content: { target: 'd1', key: 'role', value: 'core' }, refs: [ref('d1', 7)] },
      { id: 2, category: 'view_hint', kind: 'role', status: 'pending', check_status: 'reject', content: { target: 'd1', key: 'role', value: 'p' }, refs: [ref('d1', 7)] },
      { id: 3, category: 'peer_link', kind: 'peer', status: 'pending', check_status: 'warn', content: { a: 'd1', b: 'd2' }, refs: [ref('d1', 7), ref('d2', 8)] },
      { id: 4, category: 'view_hint', kind: 'group', status: 'adopted', check_status: 'pass', content: { target: 'd1', key: 'group', value: 'West' }, refs: [ref('d1', 7)] },
    ])
    expect(p.hints).toEqual([{ id: 1, device_id: 7, key: 'role', value: 'core' }])
    expect(p.peers).toEqual([{ id: 3, a: 7, b: 8, aLabel: 'dev7', bLabel: 'dev8', external: false, label: '' }])
  })
  it('badges', () => {
    expect(badgesOf({ ai: true, cons: true })).toEqual(['cons', 'ai'])
  })
})
