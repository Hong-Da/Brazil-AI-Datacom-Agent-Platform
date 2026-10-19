import { describe, expect, it } from 'vitest'
import { bootMode, counts, isLastAdmin, passwordProblems, safeNext, shortTime, stateOf, validName, type UserRow } from './account'

const row = (p: Partial<UserRow>): UserRow => ({
  id: 1, username: 'u', role: 'user', disabled: false, locked: false, locked_until: null,
  last_login_at: null, password_changed_at: null, created_at: null, ...p,
})

describe('账号逻辑', () => {
  it('密码规则', () => {
    expect(passwordProblems('short')).toEqual(['short'])
    expect(passwordProblems('long-enough', 'long-enougX')).toEqual(['mismatch'])
    expect(passwordProblems('long-enough', 'long-enough', 'long-enough')).toEqual(['same'])
    expect(passwordProblems('long-enough', 'long-enough', 'old-one-12')).toEqual([])
  })
  it('用户名规则', () => {
    expect(validName('admin')).toBe(true)
    expect(validName('ana.souza')).toBe(true)
    expect(validName('a')).toBe(false)
    expect(validName('-x')).toBe(false)
    expect(validName('名字')).toBe(false)
  })
  it('登录后只跳站内地址', () => {
    expect(safeNext('/devices?x=1')).toBe('/devices?x=1')
    expect(safeNext('//evil.example')).toBe('/')
    expect(safeNext('https://evil.example')).toBe('/')
    expect(safeNext('/login?next=/')).toBe('/')
    expect(safeNext(undefined)).toBe('/')
    expect(safeNext(['/check'])).toBe('/check')
  })
  it('状态与最后一个管理员', () => {
    const rows = [row({ id: 1, username: 'admin', role: 'admin' }), row({ id: 2, username: 'old', role: 'admin', disabled: true }), row({ id: 3, locked: true })]
    expect(rows.map(stateOf)).toEqual(['enabled', 'disabled', 'locked'])
    expect(isLastAdmin(rows[0], rows)).toBe(true)
    expect(isLastAdmin(rows[1], rows)).toBe(false)
    expect(isLastAdmin(rows[0], [...rows, row({ id: 4, role: 'admin' })])).toBe(false)
    expect(counts(rows)).toEqual({ all: 3, admin: 2, locked: 1, disabled: 1 })
  })
  it('时间显示', () => {
    expect(shortTime(null)).toBe('')
    expect(shortTime('bad')).toBe('bad')
    expect(shortTime('2026-10-18T09:12:00')).toMatch(/^2026-10-18 09:12$/)
  })
  it('第一个管理员的创建方式', () => {
    const base = { configured: true, session_hours: 12 }
    expect(bootMode(null)).toBeNull()
    expect(bootMode({ ...base, has_users: true })).toBeNull()
    expect(bootMode({ ...base, has_users: false, token_set: true, config_file: '/x/config/config.toml' })).toBe('token')
    expect(bootMode({ ...base, has_users: false, token_set: false, config_file: '/x/config/config.toml' })).toBe('cli')
    expect(bootMode({ ...base, has_users: false })).toBe('token') // 旧版后端没有 token_set
  })
})
