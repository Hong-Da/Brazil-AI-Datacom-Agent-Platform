import { describe, expect, it } from 'vitest'
import { activityKey, isProjectApi, legacyPath, legacyTarget, PROJECT_PAGE_NAMES, refFromParam, refParam, refPath, scopedPath, withProject } from './scope'

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
