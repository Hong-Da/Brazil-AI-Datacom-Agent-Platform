import { expect, request as pwRequest, test, type APIRequestContext } from '@playwright/test'
import { ADMIN, collectErrors, login, USER } from './helpers'

/**
 * M6（REQ-035 / REQ-036）项目流程：普通用户新建项目 → 引用公共设备并固定版本 → 邀请只读成员 → 只读成员看不到修改按钮。
 * 公共设备库由管理员通过接口准备（导入两个版本）；只读成员账号也由管理员建好。
 */
const READER = { username: 'e2e-reader', password: 'E2e-reader-pass' }
const PUB = 'E2E-PUB-01'
const cfg = (desc: string): string => `sysname ${PUB}\n#\ninterface GigabitEthernet0/2/1\n description ${desc}\n#\nreturn\n`

async function asUser(baseURL: string, who: { username: string; password: string }): Promise<APIRequestContext> {
  const ctx = await pwRequest.newContext({ baseURL })
  const r = await ctx.post('/api/v1/auth/login', { data: who })
  expect(r.ok(), await r.text()).toBeTruthy()
  return ctx
}

test('项目流程：新建项目、引用公共设备并固定版本、邀请只读成员', async ({ page, browser, baseURL }) => {
  test.setTimeout(120_000)
  const admin = await asUser(baseURL!, ADMIN)
  // 公共设备库：同一台设备两个版本
  for (const [i, d] of ['v1', 'v2'].entries()) {
    const r = await admin.post('/api/v1/public-devices', {
      multipart: { level: 'basic', files: { name: `pub-${i}.cfg`, mimeType: 'text/plain', buffer: Buffer.from(cfg(d)) } },
    })
    expect(r.ok(), await r.text()).toBeTruthy()
  }
  const pub = ((await (await admin.get('/api/v1/public-devices')).json()).data.devices as { id: number; name: string }[]).find((d) => d.name === PUB)!
  expect(pub).toBeTruthy()
  const created = await admin.post('/api/v1/users', { data: { ...READER, role: 'user' } })
  expect(created.ok() || created.status() === 409, await created.text()).toBeTruthy()

  const slug = `e2e-m6-${Date.now() % 100000}`
  await login(page, 'zh-CN', USER)
  const errors = collectErrors(page)
  try {
    // 新建项目（从顶栏切换器进入），建好后进入添加设备页
    await page.goto('/')
    await page.getByTestId('project-switcher-button').click()
    await page.getByTestId('sw-new').click()
    await page.getByTestId('np-name').fill('E2E 割接项目')
    await page.getByTestId('np-slug').fill(slug)
    await page.getByTestId('np-create').click()
    await expect(page).toHaveURL(new RegExp(`/p/${slug}/devices/add`))
    await expect(page.getByTestId('project-current')).toHaveText('E2E 割接项目')

    // 引用公共设备，固定在第一个版本
    await page.getByTestId('src-pub').check()
    await page.getByTestId(`add-pub-check-${pub.id}`).check()
    await page.getByTestId(`add-pub-mode-ref-${pub.id}`).click()
    await page.getByTestId(`add-pub-policy-${pub.id}`).selectOption('pin')
    const ver = page.getByTestId(`add-pub-ver-${pub.id}`)
    // 版本列表异步加载；加载前只有“最新版本”一个选项
    await expect(ver.locator('option')).toHaveCount(2)
    const values = await ver.locator('option').evaluateAll((os) => os.map((o) => (o as HTMLOptionElement).value).filter(Boolean))
    await ver.selectOption(values.map(Number).sort((a, b) => a - b)[0].toString())
    await page.getByTestId('add-submit').click()
    await expect(page.getByTestId('add-outcome-0')).toBeVisible()

    // 设备页：公共 · 固定在 v1，公共库有新版本的提示
    await page.goto(`/p/${slug}/devices`)
    await expect(page.getByTestId('devices-table')).toContainText(PUB)
    await expect(page.getByTestId('src-public')).toBeVisible()
    await expect(page.getByTestId('ver-pin')).toContainText('v1')
    await expect(page.getByTestId('newer-notice')).toBeVisible()

    // 邀请只读成员
    await page.goto(`/p/${slug}/settings`)
    await page.getByTestId('ps-invite-name').fill(READER.username)
    await page.getByTestId('ps-invite-role').selectOption('read')
    await page.getByTestId('ps-invite').click()
    await expect(page.getByTestId(`ps-member-${READER.username}`)).toBeVisible()
    expect(errors).toEqual([])

    // 只读成员：能看到设备，没有导入、添加、删除，顶部有只读说明
    const ctx = await browser.newContext()
    const rp = await ctx.newPage()
    await login(rp, 'zh-CN', READER)
    await rp.goto(`/p/${slug}/devices`)
    await expect(rp.getByTestId('devices-table')).toContainText(PUB)
    await expect(rp.getByTestId('scope-readonly')).toBeVisible()
    await expect(rp.getByTestId('open-import')).toHaveCount(0)
    await expect(rp.getByTestId('add-device')).toHaveCount(0)
    await expect(rp.getByTestId('device-delete')).toHaveCount(0)
    await rp.getByTestId('device-menu').first().click()
    await expect(rp.getByTestId('device-act-unlink')).toHaveCount(0)
    await expect(rp.getByTestId('device-act-history')).toBeVisible()
    await ctx.close()
  } finally {
    const u = await asUser(baseURL!, USER)
    await u.delete(`/api/v1/projects/${slug}?confirm=${slug}`)
    await u.dispose()
    await admin.delete(`/api/v1/public-devices/${pub.id}?force=true`)
    await admin.dispose()
  }
})

test('旧网址跳到默认项目的对应页面', async ({ page }) => {
  await login(page)
  await page.goto('/devices')
  await expect(page).toHaveURL(/\/p\/[^/]+\/devices$/)
  // M9：项目只有默认网络时，按网络的页面直接进默认网络（/p/<项目>/n/<网络>/scripts）
  await page.goto('/check-projects')
  await expect(page).toHaveURL(/\/p\/[^/]+\/n\/[^/]+\/scripts$/)
  await page.goto('/p/no-such-project/devices')
  await expect(page).toHaveURL(/\/projects\?missing=no-such-project/)
  await expect(page.getByTestId('projects-missing')).toBeVisible()
})

/**
 * 标识按属主唯一（用户 2026-10-19 评审改选）：e2e-user 与 e2e-admin 各有一个同名项目。
 * 自己的写 /p/<标识>/…，别人的写 /p/<属主>/<标识>/…；两个都能访问的账号只写标识时回到“我的项目”选择。
 */
test('同名项目：自己的与别人的互不影响，只写标识有歧义时列出候选', async ({ page, browser, baseURL }) => {
  test.setTimeout(120_000)
  const slug = `e2e-same-${Date.now() % 100000}`
  const admin = await asUser(baseURL!, ADMIN)
  const user = await asUser(baseURL!, USER)
  const both = { username: 'e2e-both', password: 'E2e-both-pass' }
  const made = await admin.post('/api/v1/users', { data: { ...both, role: 'user' } })
  expect(made.ok() || made.status() === 409, await made.text()).toBeTruthy()
  try {
    expect((await user.post('/api/v1/projects', { data: { name: '我的同名项目', slug } })).ok()).toBeTruthy()
    expect((await admin.post('/api/v1/projects', { data: { name: '管理员的同名项目', slug } })).ok()).toBeTruthy()
    // 管理员的项目：e2e-user 与 e2e-both 只读；e2e-user 的项目：e2e-both 只读
    for (const who of [USER.username, both.username]) {
      expect((await admin.put(`/api/v1/projects/${slug}/members/${who}`, { data: { role: 'read' } })).ok()).toBeTruthy()
    }
    expect((await user.put(`/api/v1/projects/${slug}/members/${both.username}`, { data: { role: 'read' } })).ok()).toBeTruthy()

    await login(page, 'zh-CN', USER)
    const errors = collectErrors(page)
    // 只写标识：自己的项目
    await page.goto(`/p/${slug}/devices`)
    await expect(page.getByTestId('project-current')).toHaveText('我的同名项目')
    await expect(page).toHaveURL(new RegExp(`/p/${slug}/devices$`))
    // 属主/标识：别人的项目（只读）
    await page.goto(`/p/${ADMIN.username}/${slug}/devices`)
    await expect(page.getByTestId('project-current')).toHaveText('管理员的同名项目')
    await expect(page.getByTestId('scope-readonly')).toBeVisible()
    // 项目切换器：两个都在，切回自己的
    await page.getByTestId('project-switcher-button').click()
    await expect(page.getByTestId(`sw-item-${ADMIN.username}/${slug}`)).toBeVisible()
    await page.getByTestId(`sw-item-${slug}`).click()
    await expect(page).toHaveURL(new RegExp(`/p/${slug}/devices$`))
    await expect(page.getByTestId('project-current')).toHaveText('我的同名项目')
    expect(errors).toEqual([])

    // 两个都能访问、自己没有同名的账号：只写标识时回到“我的项目”列出候选
    const ctx = await browser.newContext()
    const bp = await ctx.newPage()
    await login(bp, 'zh-CN', both)
    await bp.goto(`/p/${slug}/devices`)
    await expect(bp).toHaveURL((u) => u.pathname === "/projects" && u.searchParams.get("ambiguous") === slug)
    await expect(bp.getByTestId('projects-ambiguous')).toBeVisible()
    await bp.getByTestId(`projects-ambiguous-${USER.username}/${slug}`).click()
    await expect(bp).toHaveURL(new RegExp(`/p/${USER.username}/${slug}/devices$`))
    await expect(bp.getByTestId('project-current')).toHaveText('我的同名项目')
    await ctx.close()
  } finally {
    await user.delete(`/api/v1/projects/${slug}?confirm=${slug}`)
    await admin.delete(`/api/v1/projects/${slug}?confirm=${slug}`)
    await admin.delete(`/api/v1/users/${both.username}?delete_projects=true`)
    await user.dispose()
    await admin.dispose()
  }
})
