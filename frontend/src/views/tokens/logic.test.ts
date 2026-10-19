import { describe, expect, it } from 'vitest'
import { apiExample, canRemove, canRevoke, cliExample, sortTokens, type TokenRow } from './logic'

const tok = (o: Partial<TokenRow>): TokenRow => ({
  id: 1, name: 'a', prefix: 'lmp_abcd', read_only: false, created_at: '2026-10-01T00:00:00Z', expires_at: null,
  last_used_at: null, last_used_ip: null, revoked_at: null, state: 'active', ...o,
})

describe('tokens logic', () => {
  it('sorts active first, then newest', () => {
    const rows = [
      tok({ id: 1, state: 'revoked', created_at: '2026-10-05T00:00:00Z' }),
      tok({ id: 2, created_at: '2026-10-01T00:00:00Z' }),
      tok({ id: 3, created_at: '2026-10-03T00:00:00Z' }),
    ]
    expect(sortTokens(rows).map((t) => t.id)).toEqual([3, 2, 1])
  })

  it('revoke only active, remove only inactive', () => {
    expect(canRevoke(tok({}))).toBe(true)
    expect(canRemove(tok({}))).toBe(false)
    expect(canRevoke(tok({ state: 'expired' }))).toBe(false)
    expect(canRemove(tok({ state: 'revoked' }))).toBe(true)
  })

  it('examples use the project path and never a real token', () => {
    const ex = apiExample('http://h:9090', 'oam', 7)
    expect(ex[0].line).toContain('http://h:9090/api/v1/projects/oam/devices')
    expect(ex[1].line).toContain('"device_id": 7')
    expect(ex.every((e) => e.line.includes('$LMESH_TOKEN') && !e.line.includes('lmp_'))).toBe(true)
    expect(cliExample('oam', 'R1')[1]).toBe('lmesh --project oam check R1')
    expect(cliExample('oam', 'bad name', '<x>')[1]).toBe('lmesh --project oam check <x>')
  })
})
