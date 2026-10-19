import { expect, request as pwRequest, test, type APIRequestContext } from '@playwright/test'
import { ADMIN, USER, collectErrors, login } from './helpers'

/**
 * REQ-040 AI 接口——公共与个人：管理员建两个接口、只开放一个 → 用户在“我的 AI”里只看到开放的那个 →
 * 用户改用个人接口（只测保存与选择，不调用外部 AI）→ 另一个用户选了公共接口，管理员关闭公共使用后他看到改选提示。
 * 结束时删除建的接口与账号、恢复 e2e-user 的选择。
 */
async function asUser(baseURL: string, who: { username: string; password: string }): Promise<APIRequestContext> {
  const ctx = await pwRequest.newContext({ baseURL })
  const r = await ctx.post('/api/v1/auth/login', { data: who })
  expect(r.ok(), await r.text()).toBeTruthy()
  return ctx
}

test('AI 接口：公开一个、个人接口、关闭公共后提示改选', async ({ page, browser, baseURL }) => {
  test.setTimeout(150_000)
  const n = Date.now() % 100000
  const PUB = `e2e-pub-${n}`
  const PRIV = `e2e-priv-${n}`
  const OTHER = { username: `e2e-ai-${n}`, password: 'E2e-ai-pass-12' }
  const admin = await asUser(baseURL!, ADMIN)
  const ids: number[] = []
  try {
    // 管理员在 AI 接口页添加一个公开的接口（界面），另一个不公开的用接口建
    await login(page, 'zh-CN', ADMIN)
    const errors = collectErrors(page)
    await page.goto('/ai')
    await expect(page.getByTestId('ai-tabs')).toBeVisible()
    await page.getByTestId('ai-add').click()
    await expect(page).toHaveURL(/\/ai\/connections\/new$/)
    await page.getByTestId('ai-conn-f-name').fill(PUB)
    await page.getByTestId('ai-conn-f-model').fill('fake-model')
    await page.getByTestId('ai-conn-f-provider-local').check()
    await page.getByTestId('ai-conn-f-url').fill('http://127.0.0.1:9/v1')
    await page.getByTestId('ai-conn-f-public').locator('..').click() // 开关（复选框本身不可见）
    await expect(page.getByTestId('ai-conn-f-public')).toBeChecked()
    await page.getByTestId('ai-conn-save').click()
    await expect(page).toHaveURL(/\/ai\/connections\/\d+$/) // 建好后进入它的设置页
    await expect(page.getByTestId('ai-conn-saved')).toBeVisible()
    await expect(page.getByTestId('ai-usage-panel')).toBeVisible()
    await page.getByTestId('ai-conn-back').click()
    const row = page.getByTestId(`ai-conn-${PUB}`)
    await expect(row).toBeVisible()
    await expect(row.getByTestId(`ai-conn-public-${PUB}`)).toBeChecked()
    // 用量统计分区（管理员看全部）
    await page.getByTestId('ai-tab-usage').click()
    await expect(page.getByTestId('usage-totals')).toBeVisible()
    await page.getByTestId('usage-days-7').click()
    await page.getByTestId('ai-tab-conns').click()
    const made = await admin.post('/api/v1/ai/connections', { data: { name: PRIV, provider: 'local', base_url: 'http://127.0.0.1:9/v1', model: 'm2', public: false } })
    expect(made.ok(), await made.text()).toBeTruthy()
    const list = (await (await admin.get('/api/v1/ai/connections')).json()).data.connections as { id: number; name: string }[]
    for (const c of list) if (c.name === PUB || c.name === PRIV) ids.push(c.id)
    expect(ids).toHaveLength(2)
    const pubId = list.find((c) => c.name === PUB)!.id
    expect(errors).toEqual([])

    // 另一个用户：选用公开的接口
    expect((await admin.post('/api/v1/users', { data: { ...OTHER, role: 'user' } })).ok()).toBeTruthy()
    const other = await asUser(baseURL!, OTHER)
    const chose = await other.put('/api/v1/me/ai', { data: { choice: 'connection', connection_id: pubId } })
    expect(chose.ok(), await chose.text()).toBeTruthy()
    await other.dispose()

    // e2e-user：从账号菜单进入“我的 AI”，只看到公开的接口；改用个人接口并保存
    const ctx = await browser.newContext()
    const up = await ctx.newPage()
    await login(up, 'zh-CN', USER)
    const uerr = collectErrors(up)
    await up.goto('/')
    await up.getByTestId('user-menu-button').click()
    await up.getByTestId('menu-my-ai').click()
    await expect(up).toHaveURL(/\/me\/ai$/)
    await expect(up.getByTestId(`my-ai-src-${PUB}`)).toBeVisible()
    await expect(up.getByTestId(`my-ai-src-${PRIV}`)).toHaveCount(0)
    await expect(up.getByTestId('my-ai-usage')).toBeVisible()
    await up.getByTestId('my-ai-edit-personal').click()
    await expect(up).toHaveURL(/\/me\/ai\/personal$/)
    await up.getByTestId('my-ai-p-provider-local').check()
    await up.getByTestId('my-ai-p-url').fill('http://127.0.0.1:9/v1')
    await up.getByTestId('my-ai-p-model').fill('my-model')
    await expect(up.getByTestId('my-ai-p-use')).toBeChecked() // 保存时同时改用个人 API
    await up.getByTestId('my-ai-p-save').click()
    await expect(up.getByTestId('my-ai-p-saved')).toBeVisible()
    await up.getByTestId('my-ai-p-back').click()
    await expect(up.getByTestId('my-ai-src-personal')).toHaveClass(/is-on/)
    await expect(up.getByTestId('my-ai-eff-name')).toBeVisible()
    const mine = (await (await up.request.get('/api/v1/me/ai')).json()).data
    expect(mine.choice).toBe('personal')
    expect(mine.effective.source).toBe('personal')
    expect(JSON.stringify(mine)).not.toContain('api_key"') // 只有 api_key_set
    expect(uerr).toEqual([])
    await ctx.close()

    // 管理员关闭公共使用 → 选了它的用户看到改选提示
    await page.reload()
    await page.getByTestId(`ai-conn-public-${PUB}`).locator('..').click()
    await expect(page.getByTestId(`ai-conn-public-${PUB}`)).not.toBeChecked()
    const ctx2 = await browser.newContext()
    const op = await ctx2.newPage()
    await login(op, 'zh-CN', OTHER)
    await op.goto('/me/ai')
    await expect(op.getByTestId('my-ai-closed')).toBeVisible()
    await expect(op.getByTestId('my-ai-src-closed')).toBeVisible()
    await expect(op.getByTestId('ai-off-public_closed')).toBeVisible()
    await ctx2.close()
  } finally {
    for (const id of ids) await admin.delete(`/api/v1/ai/connections/${id}`)
    const u = await asUser(baseURL!, USER).catch(() => null)
    if (u) { await u.put('/api/v1/me/ai', { data: { choice: 'auto', remove_personal: true } }); await u.dispose() }
    await admin.delete(`/api/v1/users/${OTHER.username}?delete_projects=true`)
    await admin.dispose()
  }
})
