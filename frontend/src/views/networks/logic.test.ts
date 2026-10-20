import { describe, expect, it } from 'vitest'
import {
  colorClass, filterMembers, globMatch, joinOf, joinedRecently, matchNet, netActivityKey, netDevFilter, netName, netOrder, netTree,
  outsideKey, overlapMatrix, peerStubs, slugify, SLUG_RE, sumKindOf, type Member, type NetList, type NetRow, type OutsideLink,
} from './logic'

const counts = { devices: 0, shared: 0, pinned: 0, scripts: 0, scripts_with_errors: 0, check_groups: 0, ai_pending: 0, annotations: 0, ignores: 0, overrides: 0, rules: 0, findings: { error: 0, warning: 0, info: 0, devices_checked: 0, last_run: null } }
function net(id: number, slug: string, o: Partial<NetRow> = {}): NetRow {
  return { id, slug, name: slug, color: 'indigo', default: false, description: null, folder_id: null, folder: null, position: id, copied_from: null, last_activity: null, created_by: null, created_at: null, updated_at: null, counts, ...o }
}
const LIST: Pick<NetList, 'networks' | 'folders'> = {
  networks: [net(3, 'west', { folder_id: 9, position: 2 }), net(2, 'east', { folder_id: 9, position: 1 }), net(4, 'core', { position: 5 }), net(1, 'default', { default: true, position: 9, color: 'slate', name: '默认网络' })],
  folders: [{ id: 9, name: 'IP RAN', position: 1, networks: ['east', 'west'] }],
}

describe('网络列表与识别色', () => {
  it('识别色类：8 色之一，不认识的用 slate', () => {
    expect(colorClass('teal')).toBe('nc-teal')
    expect(colorClass('pink')).toBe('nc-slate')
    expect(colorClass(null)).toBe('nc-slate')
  })
  it('默认网络的中文默认名称按语言显示，改过名的照原样', () => {
    expect(netName({ name: '默认网络', default: true }, 'Default network')).toBe('Default network')
    expect(netName({ name: '管理网', default: true }, 'Default network')).toBe('管理网')
    expect(netName({ name: '默认网络', default: false }, 'Default network')).toBe('默认网络')
    expect(netName(null, 'x')).toBe('')
  })
  it('标识：小写字母、数字、连字符', () => {
    expect(slugify('IP RAN East')).toBe('ip-ran-east')
    expect(slugify('城域核心', 'net')).toBe('net')
    expect(slugify('--A__b--')).toBe('a-b')
    expect(SLUG_RE.test('ip-ran-east')).toBe(true)
    expect(SLUG_RE.test('-bad')).toBe(false)
    expect(SLUG_RE.test('Bad')).toBe(false)
  })
  it('顺序：最外层（默认网络在前，再按位置），然后各文件夹', () => {
    const t = netTree(LIST)
    expect(t.root.map((n) => n.slug)).toEqual(['default', 'core'])
    expect(t.folders[0].nets.map((n) => n.slug)).toEqual(['east', 'west'])
    expect(netOrder(LIST).map((n) => n.slug)).toEqual(['default', 'core', 'east', 'west'])
    expect(netTree(null)).toEqual({ root: [], folders: [] })
  })
  it('搜索：名称、标识、译名或文件夹名', () => {
    expect(matchNet({ name: '东区', slug: 'east' }, 'EA')).toBe(true)
    expect(matchNet({ name: '东区', slug: 'east' }, '东')).toBe(true)
    expect(matchNet({ name: '东区', slug: 'east' }, 'ran', 'IP RAN')).toBe(true)
    expect(matchNet({ name: '默认网络', slug: 'default' }, 'network', null, 'Default network')).toBe(true)
    expect(matchNet({ name: '东区', slug: 'east' }, 'west')).toBe(false)
    expect(matchNet({ name: '东区', slug: 'east' }, '  ')).toBe(true)
  })
  it('共用矩阵：两两共用的设备数，对角线为网络大小', () => {
    const nets = [{ id: 1 }, { id: 2 }, { id: 3 }]
    const devs = [{ networks: [{ id: 1 }, { id: 2 }, { id: 3 }] }, { networks: [{ id: 1 }, { id: 2 }] }, { networks: [{ id: 1 }] }, {}]
    expect(overlapMatrix(nets, devs)).toEqual([[3, 2, 1], [2, 2, 1], [1, 1, 1]])
  })
  it('汇总页按页面选指标', () => {
    expect(sumKindOf('check')).toBe('findings')
    expect(sumKindOf('baseline')).toBe('findings')
    expect(sumKindOf('check-project')).toBe('scripts')
    expect(sumKindOf('topology')).toBe('topology')
    expect(sumKindOf('members')).toBe('members')
    expect(sumKindOf('change')).toBe('devices')
  })
  it('最近活动映射为文案键', () => {
    expect(netActivityKey('create')).toBe('create')
    expect(netActivityKey('members.add')).toBe('members_add')
    expect(netActivityKey('PUT /view-annotations')).toBe('annotations')
    expect(netActivityKey('POST /ai/suggestions/7/adopt')).toBe('ai')
    expect(netActivityKey('PUT /rules/R1')).toBe('rules')
    expect(netActivityKey('POST /configs')).toBe('import')
    expect(netActivityKey('GET /x')).toBeNull()
    expect(netActivityKey(null)).toBeNull()
  })
})

describe('拓扑：网络外的对端', () => {
  const link = (id: string, inside: string, peer: string, nets: string[] = ['west']): OutsideLink => ({
    id, type: 'subnet', inside: { device: inside, interface: 'GE0/0/1' }, peer: { device: peer, device_id: 9, networks: nets.map((s, i) => ({ id: i + 10, slug: s, name: s, color: 'rust', default: false })) },
  })
  it('按对端设备归并，记下本网络里连过去的设备', () => {
    const s = peerStubs([link('a', 'e1', 'hub2'), link('b', 'e2', 'hub2'), link('c', 'e1', 'hub10', [])])
    expect(s.map((x) => x.id)).toEqual(['out:hub2', 'out:hub10'])
    expect(s[0].links).toHaveLength(2)
    expect(s[0].inside).toEqual(['e1', 'e2'])
    expect(s[0].networks.map((n) => n.slug)).toEqual(['west'])
    expect(s[1].networks).toEqual([])
  })
  it('开关按账号、项目、网络记在浏览器里', () => {
    expect(outsideKey('li', 'oam', 'east')).toBe('lmesh-net-outside:li:oam:east')
    expect(outsideKey(null, undefined, null)).toBe('lmesh-net-outside:::')
  })
})

describe('成员', () => {
  const now = Date.parse('2026-10-20T12:00:00Z')
  function mem(name: string, o: Partial<Member> = {}): Member {
    return { device_id: name.length, name, vendor: 'huawei', platform: null, profile: null, source: 'private', versions: 2, latest_version_id: 2, latest_seq: 2, policy: 'follow', version_id: 2, seq: 2, newer_available: false, also_in: [], join_source: 'manual', rule: null, joined_by: 'li', joined_at: '2026-10-01T00:00:00Z', mgmt_address: '10.0.0.1', ...o }
  }
  const list = [
    mem('a-1', { also_in: [{ id: 1, slug: 'default', name: 'd', color: 'slate', default: true }] }),
    mem('b-22', { also_in: [{ id: 3, slug: 'west', name: 'w', color: 'rust', default: false }] }),
    mem('c-333', { policy: 'pin', joined_at: '2026-10-20T08:00:00Z', mgmt_address: '10.9.9.9' }),
  ]
  it('过滤：也在其他非默认网络、固定版本、24 小时内加入、按名称或管理地址搜索', () => {
    expect(filterMembers(list, '', 'shared', now).map((m) => m.name)).toEqual(['b-22'])
    expect(filterMembers(list, '', 'pin', now).map((m) => m.name)).toEqual(['c-333'])
    expect(filterMembers(list, '', 'new', now).map((m) => m.name)).toEqual(['c-333'])
    expect(filterMembers(list, '10.9', '', now).map((m) => m.name)).toEqual(['c-333'])
    expect(filterMembers(list, 'B-2', '', now).map((m) => m.name)).toEqual(['b-22'])
    expect(joinedRecently({ joined_at: null }, now)).toBe(false)
  })
  it('加入方式的文案键与图标', () => {
    expect(joinOf('upgrade')).toEqual({ key: 'default', icon: 'layers' })
    expect(joinOf('rule').key).toBe('rule')
    expect(joinOf('suggestion').icon).toBe('wand')
    expect(joinOf('import').key).toBe('import')
    expect(joinOf('whatever').key).toBe('manual')
  })
  it('设备名通配与后端一致（不分大小写，* ?）', () => {
    expect(globMatch('ran-e-*', 'RAN-E-ACC01')).toBe(true)
    expect(globMatch('ran-?-agg01', 'ran-w-agg01')).toBe(true)
    expect(globMatch('ran.e*', 'ranxe1')).toBe(false)
    expect(globMatch('mc-p0*', 'oob-sw01')).toBe(false)
  })
})

describe('设备页的网络过滤', () => {
  const d = (slugs: string[], policy?: string) => ({ networks: [{ slug: 'default', default: true }, ...slugs.map((s) => ({ slug: s, default: false }))], network_policy: policy })
  const rows = [d([]), d(['east']), d(['east', 'west'], 'pin')]
  it('项目层：多个网络 / 只在默认网络 / 在某个网络', () => {
    expect(netDevFilter(rows, '')).toHaveLength(3)
    expect(netDevFilter(rows, 'several')).toEqual([rows[2]])
    expect(netDevFilter(rows, 'only')).toEqual([rows[0]])
    expect(netDevFilter(rows, 'n:east')).toEqual([rows[1], rows[2]])
  })
  it('网络里：也在其他网络、本网络固定了版本', () => {
    expect(netDevFilter(rows, 'several', 'east')).toEqual([rows[2]])
    expect(netDevFilter(rows, 'pin', 'east')).toEqual([rows[2]])
  })
})
