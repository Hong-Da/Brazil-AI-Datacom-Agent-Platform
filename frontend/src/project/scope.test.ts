import { describe, expect, it } from 'vitest'
import {
  activityKey, basePage, isProjectApi, legacyPath, legacyTarget, netName, networkable, networkPath, pageNet, PROJECT_PAGE_NAMES, refFromParam, refParam, refPath,
  scopedPath, withNetwork, withProject,
} from './scope'

describe('项目路径改写', () => {
  it('设备相关接口改走 /projects/<项目>/…，查询参数保留', () => {
    expect(scopedPath('/devices', 'oam')).toBe('/projects/oam/devices')
    expect(scopedPath('/devices/12/graph?raw=true', 'oam')).toBe('/projects/oam/devices/12/graph?raw=true')
    expect(scopedPath('/check-projects/3/scripts/9/revisions/2/restore', 'oam')).toBe('/projects/oam/check-projects/3/scripts/9/revisions/2/restore')
    expect(scopedPath('/summary', 'a-b')).toBe('/projects/a-b/summary')
    // 别人的项目（属主/标识）：编码成 %2F，后端在路由前还原
    expect(scopedPath('/devices', 'liwei/oam')).toBe('/projects/liwei%2Foam/devices')
  })
  it('全局接口、已带项目的路径、没有当前项目时原样返回', () => {
    expect(scopedPath('/kb/schema', 'oam')).toBe('/kb/schema')
    expect(scopedPath('/templates', 'oam')).toBe('/templates')
    expect(scopedPath('/templates/check', 'oam')).toBe('/projects/oam/templates/check')
    expect(scopedPath('/projects/x/devices', 'oam')).toBe('/projects/x/devices')
    expect(scopedPath('/devices', null)).toBe('/devices')
    expect(scopedPath('/public-devices', 'oam')).toBe('/public-devices')
  })
  it('只按整段匹配', () => {
    expect(isProjectApi('/devices/1/versions/2/text')).toBe(true)
    expect(isProjectApi('/devices/1/unknown-thing')).toBe(false)
    expect(isProjectApi('/devicesx')).toBe(false)
  })
})

describe('页面路由', () => {
  it('旧网址跳到当前项目，配置检查项目改为项目脚本', () => {
    expect(legacyTarget('/graph/12?node=x', 'oam')).toBe('/p/oam/graph/12?node=x')
    expect(legacyTarget('/check-projects', 'oam')).toBe('/p/oam/scripts')
    expect(legacyTarget('/check-projects/4?script=2', 'oam')).toBe('/p/oam/scripts/4?script=2')
    expect(legacyTarget('/check?device=1', 'oam')).toBe('/p/oam/check?device=1')
    expect(legacyTarget('/graph/12', 'liwei/oam')).toBe('/p/liwei/oam/graph/12')
  })
  it('项目引用与路由参数（标识按属主唯一）', () => {
    expect(refParam('oam')).toEqual(['oam'])
    expect(refParam('liwei/oam')).toEqual(['liwei', 'oam'])
    expect(refPath('li wei/oam')).toBe('li%20wei/oam')
    expect(refFromParam(['liwei', 'oam'])).toBe('liwei/oam')
    expect(refFromParam('oam')).toBe('oam')
    expect(refFromParam(['a', 'b', 'c'])).toBeNull()
    expect(refFromParam([])).toBeNull()
  })
  it('去项目页面时补上当前项目，已有或不是项目页面时不变', () => {
    expect(withProject({ name: 'devices' }, 'oam')).toEqual({ name: 'devices', params: { project: ['oam'] } })
    expect(withProject({ name: 'device-graph', params: { id: 3 } }, 'oam')).toEqual({ name: 'device-graph', params: { id: 3, project: ['oam'] } })
    expect(withProject({ name: 'devices', params: { project: 'x' } }, 'oam')).toEqual({ name: 'devices', params: { project: ['x'] } })
    // 别人的项目：网址是 /p/属主/标识/…
    expect(withProject({ name: 'devices' }, 'liwei/oam')).toEqual({ name: 'devices', params: { project: ['liwei', 'oam'] } })
    expect(withProject({ name: 'devices', params: { project: 'zhang/oam' } }, 'oam')).toEqual({ name: 'devices', params: { project: ['zhang', 'oam'] } })
    expect(withProject({ name: 'devices', params: { project: ['zhang', 'oam'] } }, 'oam')).toEqual({ name: 'devices', params: { project: ['zhang', 'oam'] } })
    expect(withProject({ name: 'templates' }, 'oam')).toEqual({ name: 'templates' })
    expect(withProject('/devices', 'oam')).toBe('/devices')
    // 还没有当前项目：改用旧网址（守卫再跳到当前项目）
    expect(withProject({ name: 'devices' }, null)).toEqual({ path: '/devices', query: undefined, hash: undefined })
    expect(withProject({ name: 'device-graph', params: { id: 3 }, query: { node: 'x' } }, null)).toEqual({ path: '/graph/3', query: { node: 'x' }, hash: undefined })
    expect(legacyPath('history')).toBe('/history')
    expect(legacyPath('check-project', { id: 4 })).toBe('/check-projects/4')
    expect(legacyPath('project-settings')).toBe('/projects')
    expect(PROJECT_PAGE_NAMES.has('scripts')).toBe(true)
  })
})

describe('最近活动', () => {
  it('“方法 路由”映射为文案键，映射不到为 null', () => {
    expect(activityKey('POST /configs')).toBe('import')
    expect(activityKey('create')).toBe('create')
    expect(activityKey('PUT ')).toBe('settings')
    expect(activityKey('PUT /refs/{device_id}')).toBe('refs')
    expect(activityKey('PUT /check-projects/{pid}/scripts/{sid}')).toBe('editScript')
    expect(activityKey('POST /something/else')).toBeNull()
    expect(activityKey(null)).toBeNull()
  })
})

describe('网络（M9）', () => {
  it('页面名称：网络层路由 n-<页面>，basePage 去掉前缀，pageNet 给出网络维度', () => {
    expect(netName('topology')).toBe('n-topology')
    expect(basePage('n-topology')).toBe('topology')
    expect(basePage('topology')).toBe('topology')
    expect(basePage('n-unknown-page')).toBe('n-unknown-page')
    expect(pageNet('n-check')).toBe('net')
    expect(pageNet('devices')).toBe('both')
    expect(pageNet('network-home')).toBe('only')
    expect(pageNet('model-rules')).toBeUndefined()
    expect(pageNet('networks')).toBeUndefined()
    expect(PROJECT_PAGE_NAMES.has('n-scripts')).toBe(true)
    expect(PROJECT_PAGE_NAMES.has('n-model-rules')).toBe(false)
    expect(legacyPath('n-check-project', { id: 4 })).toBe('/check-projects/4')
  })
  it('跳转时带上当前网络；network 为 null 时回到项目层；项目层页面去掉 network', () => {
    expect(withNetwork({ name: 'topology' }, 'core')).toEqual({ name: 'n-topology', params: { network: 'core' } })
    expect(withNetwork({ name: 'topology' }, null)).toEqual({ name: 'topology', params: {} })
    expect(withNetwork({ name: 'topology', params: { network: 'east' } }, 'core')).toEqual({ name: 'n-topology', params: { network: 'east' } })
    expect(withNetwork({ name: 'n-topology', params: { project: ['p'], network: null } }, 'core')).toEqual({ name: 'topology', params: { project: ['p'] } })
    // 已经是网络层路由、没给 network：交给 vue-router 沿用当前参数
    const keep = { name: 'n-check', query: { device: '1' } }
    expect(withNetwork(keep, 'core')).toBe(keep)
    // 只有网络层的页面没有网络时去网络列表
    expect(withNetwork({ name: 'network-home' }, null)).toEqual({ name: 'networks', params: {} })
    expect(withNetwork({ name: 'network-home', params: { network: 'core' } }, null)).toEqual({ name: 'n-network-home', params: { network: 'core' } })
    // 只在项目层的页面：不带网络
    expect(withNetwork({ name: 'model-rules' }, 'core')).toEqual({ name: 'model-rules' })
    expect(withNetwork({ name: 'model-rules', params: { project: 'p', network: null } }, 'core')).toEqual({ name: 'model-rules', params: { project: 'p' } })
    expect(withNetwork({ name: 'templates' }, 'core')).toEqual({ name: 'templates' })
    expect(withNetwork('/devices', 'core')).toBe('/devices')
    // 与 withProject 组合：/p/<项目>/n/<网络>/…
    expect(withProject(withNetwork({ name: 'scripts' }, 'core'), 'liwei/oam')).toEqual({ name: 'n-scripts', params: { network: 'core', project: ['liwei', 'oam'] } })
  })
  it('接口路径：当前项目里按网络的接口改走 /n/<网络>/，项目层接口不改', () => {
    expect(networkPath('/projects/oam/topology', 'oam', 'core')).toBe('/projects/oam/n/core/topology')
    expect(networkPath('/projects/oam/devices/3/graph?raw=1', 'oam', 'core')).toBe('/projects/oam/n/core/devices/3/graph?raw=1')
    expect(networkPath('/projects/liwei%2Foam/check', 'liwei/oam', 'core')).toBe('/projects/liwei%2Foam/n/core/check')
    // 只在项目路径下、按网络的接口（视图标注、AI 建议、规则调整、脚本）
    expect(networkPath('/projects/oam/view-annotations', 'oam', 'core')).toBe('/projects/oam/n/core/view-annotations')
    expect(networkPath('/projects/oam/ai/suggestions?status=pending', 'oam', 'core')).toBe('/projects/oam/n/core/ai/suggestions?status=pending')
    expect(networkPath('/projects/oam/rules/R1', 'oam', 'core', 'PUT')).toBe('/projects/oam/n/core/rules/R1')
    // 项目层：删除设备与版本、删除预览、版本标签、型号规则、网络管理、成员、引用、项目本身
    expect(networkPath('/projects/oam/devices/3', 'oam', 'core', 'DELETE')).toBe('/projects/oam/devices/3')
    expect(networkPath('/projects/oam/devices/3', 'oam', 'core', 'GET')).toBe('/projects/oam/n/core/devices/3')
    expect(networkPath('/projects/oam/devices/3/delete-preview', 'oam', 'core')).toBe('/projects/oam/devices/3/delete-preview')
    expect(networkPath('/projects/oam/devices/3/history/9/tag', 'oam', 'core', 'PUT')).toBe('/projects/oam/devices/3/history/9/tag')
    expect(networkPath('/projects/oam/model-rules/test', 'oam', 'core', 'POST')).toBe('/projects/oam/model-rules/test')
    expect(networkPath('/projects/oam/networks', 'oam', 'core')).toBe('/projects/oam/networks')
    expect(networkPath('/projects/oam/members/li', 'oam', 'core', 'PUT')).toBe('/projects/oam/members/li')
    expect(networkPath('/projects/oam/ai/kb/sanitize-redact', 'oam', 'core', 'POST')).toBe('/projects/oam/ai/kb/sanitize-redact')
    expect(networkPath('/projects/oam', 'oam', 'core')).toBe('/projects/oam')
    // 已带网络、别的项目、没有当前网络：原样
    expect(networkPath('/projects/oam/n/east/topology', 'oam', 'core')).toBe('/projects/oam/n/east/topology')
    expect(networkPath('/projects/other/topology', 'oam', 'core')).toBe('/projects/other/topology')
    expect(networkPath('/projects/oam/topology', 'oam', null)).toBe('/projects/oam/topology')
    expect(networkable('GET', '/scripts')).toBe(true)
    expect(networkable('POST', '/refs')).toBe(false)
    // 与 scopedPath 组合：旧路径先改成项目路径，再改成网络路径
    expect(networkPath(scopedPath('/consistency', 'oam'), 'oam', 'core', 'POST')).toBe('/projects/oam/n/core/consistency')
  })
})
