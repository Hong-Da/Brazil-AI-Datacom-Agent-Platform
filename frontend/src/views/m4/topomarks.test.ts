import { describe, expect, it } from 'vitest'
import { bandLayout, bandOfRole, buildMarks, useBands } from './topomarks'
import type { Annotation, PendingSuggestion } from '@/components/devicon/logic'
import type { TopoNode } from './topology'

const node = (id: string, device_id: number | null, profile = 'huawei-atn-v800r025', family = 'huawei-vrp8', issues = 0): TopoNode =>
  ({ id, device_id, version_id: null, source: '', profile, family, loopbacks: [], lsr_id: null, asn: null, interfaces: 1, links: 1, issues })
const anno = (target: string, key: string, value: unknown, source: 'user' | 'ai' = 'user', type = 'device', id = 1): Annotation =>
  ({ id, target_type: type, target, key, value, source, suggestion_id: null, updated_by: '', updated_at: null })
const sug = (id: number, category: string, content: Record<string, unknown>, refs: [string, number | null][], check = 'pass'): PendingSuggestion =>
  ({ id, category, kind: '', status: 'pending', check_status: check, content, refs: refs.map(([rid, d]) => ({ id: rid, found: true, device_id: d, label: rid })) })

describe('topology marks', () => {
  const nodes = [node('A1', 1, 'huawei-atn-v800r025', 'huawei-vrp8', 2), node('AGG', 2, 'cisco-iosxe-asr920', 'cisco-iosxe'), node('up.cfg', null)]
  it('roles, ghosts, badges and groups', () => {
    const r = buildMarks({
      nodes,
      annotations: [anno('1', 'role', 'access', 'ai'), anno('1', 'group', 'West'), anno('2', 'layer', 1)],
      pending: [sug(5, 'view_hint', { target: 'd2', key: 'role', value: 'aggregation' }, [['d2', 2]]), sug(6, 'view_hint', { target: 'd1', key: 'role', value: 'core' }, [['d1', 1]], 'reject')],
      stale: { 2: true },
      showAi: true,
    })
    const a1 = r.marks.get('A1')!
    expect(a1).toMatchObject({ glyph: 'access', ghost: false, group: 'West', vendor: 'hw', badges: ['cons'] })
    expect(a1.resolved.source).toBe('ai')
    const agg = r.marks.get('AGG')!
    expect(agg).toMatchObject({ glyph: 'agg', ghost: true, pendingRole: 'aggregation', layer: 1, vendor: 'cs' })
    expect(agg.badges).toEqual(['stale', 'ai'])
    expect(r.marks.get('up.cfg')!.resolved).toMatchObject({ source: 'platform', glyph: 'plat_atn' })
    const off = buildMarks({ nodes, annotations: [], pending: [sug(5, 'view_hint', { target: 'd2', key: 'role', value: 'pe' }, [['d2', 2]])], showAi: false })
    expect(off.marks.get('AGG')!.ghost).toBe(false)
    expect(useBands(off.marks)).toBe(false)
    expect(useBands(r.marks)).toBe(true)
  })
  it('adopted and pending peers become extra nodes and edges', () => {
    const r = buildMarks({
      nodes,
      annotations: [anno('1|10.9.9.9', 'peer', { a: { device_id: 1, name: 'A1', interface: 'GE0/1', address: '10.9.9.10' }, b: { device_id: null, name: '', interface: null, address: '10.9.9.9' }, external: true, label: 'AS 65010' }, 'ai', 'link', 9)],
      pending: [sug(7, 'peer_link', { a: 'd1', b: 'd2' }, [['d1', 1], ['d2', 2]])],
      showAi: true,
    })
    expect(r.extraNodes).toEqual([{ id: 'ext:10.9.9.9', label: '10.9.9.9', glyph: 'peer', ghost: false }])
    expect(r.extraEdges).toEqual([
      { id: 'peer:9', source: 'A1', target: 'ext:10.9.9.9', kind: 'peer', label: 'AS 65010' },
      { id: 'ai:7', source: 'A1', target: 'AGG', kind: 'ai', label: '' },
    ])
  })
  it('band layout: ungrouped column first, rows by band', () => {
    expect(bandOfRole('core')).toBe(1)
    expect(bandOfRole('pe')).toBe(2)
    expect(bandOfRole(null)).toBe(3)
    const pos = bandLayout([{ id: 'x', group: 'B', band: 1 }, { id: 'y', group: '', band: 3 }, { id: 'z', group: 'B', band: 3 }], 100, 50)
    expect(pos.get('y')).toEqual({ x: 0, y: 150 })
    expect(pos.get('x')!.y).toBe(50)
    expect(pos.get('x')!.x).toBeGreaterThan(0)
    expect(pos.get('z')!.x).toBe(pos.get('x')!.x)
  })
})
