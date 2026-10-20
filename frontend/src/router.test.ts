import { beforeAll, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

// 网络层路由（M9）：/p/<项目>/n/<网络>/… 不能被项目层路由（:project+ 可以吞下多段）当成项目“a/n/b”
describe('路由排序', () => {
  let router: typeof import('./router').router
  beforeAll(async () => {
    setActivePinia(createPinia())
    router = (await import('./router')).router
  })
  it.each([
    ['/p/a/n/b/analysis/12', 'n-device-analysis', ['a'], 'b'],
    ['/p/a/n/b/scripts/5', 'n-check-project', ['a'], 'b'],
    ['/p/a/n/b/graph/3', 'n-device-graph', ['a'], 'b'],
    ['/p/a/n/b/history', 'n-history', ['a'], 'b'],
    ['/p/a/n/b/topology', 'n-topology', ['a'], 'b'],
    ['/p/li/oam/n/core/check', 'n-check', ['li', 'oam'], 'core'],
    ['/p/a/n/b', 'n-network-home', ['a'], 'b'],
  ])('%s → %s', (path, name, project, network) => {
    const r = router.resolve(path)
    expect(r.name).toBe(name)
    expect(r.params.project).toEqual(project)
    expect(r.params.network).toBe(network)
  })
  it('项目层网址仍是项目层路由', () => {
    expect(router.resolve('/p/a/analysis/12').name).toBe('device-analysis')
    expect(router.resolve('/p/li/oam/scripts').name).toBe('scripts')
    expect(router.resolve('/p/a/networks/suggest').name).toBe('network-suggest')
  })
})
