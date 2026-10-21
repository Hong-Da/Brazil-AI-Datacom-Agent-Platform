import { expect, request as pwRequest, test, type APIRequestContext, type Page } from '@playwright/test'
import { ADMIN, collectErrors, login } from './helpers'

/**
 * M9-8（REQ-050）创建项目的权限与加入项目：总开关关闭时没有项目的账号看到等人邀请的提示并申请创建权限、管理员在账号管理里
 * 授权；发现项目并申请加入、属主审批时给“管理”角色、导航上的数字；邀请链接只显示一次、打开后直接加入；暗色主题。
 * 用例开始时关闭“普通用户可以创建项目”，结束时恢复（端到端服务默认打开，保持其他用例的前提）。
 */

const BASE = `http://127.0.0.1:${Number(process.env.LMESH_E2E_PORT || 9310)}`
const PW = 'M98-pass-word'
let admin: APIRequestContext

async function apiAs(who: { username: string; password: string }): Promise<APIRequestContext> {
  const ctx = await pwRequest.newContext({ baseURL: BASE })
  const r = await ctx.post('/api/v1/auth/login', { data: who })
  expect(r.ok(), await r.text()).toBeTruthy()
  return ctx
}
async function setSwitch(on: boolean): Promise<void> {
  const r = await admin.put('/api/v1/settings', { data: { values: { 'auth.user_create_projects': on } } })
  expect(r.ok(), await r.text()).toBeTruthy()
}
async function newUser(name: string): Promise<{ username: string; password: string }> {
  const r = await admin.post('/api/v1/users', { data: { username: name, password: PW, role: 'user' } })
  expect(r.ok() || r.status() === 409, await r.text()).toBeTruthy()
  return { username: name, password: PW }
}

test.beforeAll(async () => {
  admin = await apiAs(ADMIN)
  await setSwitch(false)
})
test.afterAll(async () => {
  await setSwitch(true)
  await admin.dispose()
})

test('没有项目也不能创建：提示等人邀请，一键申请创建权限，管理员授权后可以新建', async ({ page, browser }) => {
  const errors = collectErrors(page)
  const who = await newUser('m98-newbie')
  await login(page, 'zh-CN', who)
  await page.goto('/')
  await expect(page).toHaveURL(/\/projects$/)
  const wait = page.getByTestId('projects-wait')
  await expect(wait).toContainText('你还没有加入任何项目，请联系项目负责人把你加为成员')
  await expect(page.getByTestId('projects-new')).toBeDisabled()
  await expect(page.getByTestId('projects-new-locked')).toBeVisible()
  await page.getByTestId('ask-create').click()
  await page.getByTestId('create-reason').fill('负责新园区的网络规划')
  await page.getByTestId('create-send').click()
  await expect(page.getByTestId('create-request-pending')).toBeVisible()

  // 管理员：导航上有数字，账号管理里授权
  const ap = await (await browser.newContext()).newPage()
  await login(ap, 'zh-CN', ADMIN)
  await ap.goto('/users')
  await expect(ap.getByTestId('nav-users').locator('.count')).toHaveText(/[1-9]/)
  await expect(ap.getByTestId('create-switch-strip')).toContainText('普通用户可以创建项目')
  await ap.getByTestId('cr-grant-m98-newbie').click()
  await expect(ap.getByTestId('cr-m98-newbie')).toHaveCount(0)
  await expect(ap.getByTestId('user-create-switch-m98-newbie')).toBeChecked()
  await ap.context().close()

  await page.reload()
  await expect(page.getByTestId('projects-new')).toBeEnabled()
  await expect(page.getByTestId('projects-wait')).toHaveCount(0)
  expect(errors).toEqual([])
})

test('发现项目并申请加入；属主审批时给“管理”角色，“管理”成员不能删除项目', async ({ page, browser }) => {
  const errors = collectErrors(page)
  // 管理员的项目 m98-lab，设为可被搜索
  let r = await admin.post('/api/v1/projects', { data: { name: 'M98 实验局', slug: 'm98-lab', description: '园区核心网改造' } })
  expect(r.ok() || r.status() === 409, await r.text()).toBeTruthy()
  r = await admin.put('/api/v1/projects/m98-lab', { data: { discoverable: true } })
  expect(r.ok(), await r.text()).toBeTruthy()

  const who = await newUser('m98-joiner')
  await login(page, 'en', who)
  await page.goto('/discover')
  const row = page.getByTestId('discover-e2e-admin/m98-lab')
  await expect(row).toContainText('M98 实验局')
  await expect(row).toContainText('e2e-admin')
  await page.getByTestId('discover-q').fill('园区')
  await expect(row.locator('mark.hl')).toHaveText('园区')
  await page.getByTestId('discover-ask-e2e-admin/m98-lab').click()
  await page.getByTestId('join-role-edit').check()
  await page.getByTestId('join-reason').fill('I write the cutover scripts')
  await page.getByTestId('join-send').click()
  await expect(row).toContainText('Pending')
  await page.goto('/projects')
  await expect(page.getByTestId('my-join-requests')).toContainText('M98 实验局')

  // 属主：导航数字、项目设置里审批并改成“管理”
  const ap = await (await browser.newContext()).newPage()
  await login(ap, 'zh-CN', ADMIN)
  await ap.goto('/projects')
  await expect(ap.getByTestId('nav-projects').locator('.count')).toHaveText(/[1-9]/)
  await expect(ap.getByTestId('approve-strip-m98-lab')).toBeVisible()
  await ap.goto('/p/m98-lab/settings')
  await expect(ap.getByTestId('ps-discoverable-switch')).toBeChecked()
  const jr = ap.getByTestId('jr-m98-joiner')
  await expect(jr).toContainText('I write the cutover scripts')
  await ap.getByTestId('jr-role-m98-joiner').selectOption('manage')
  await ap.getByTestId('jr-approve-m98-joiner').click()
  await expect(jr).toHaveCount(0)
  await expect(ap.getByTestId('ps-member-m98-joiner')).toBeVisible()
  await ap.context().close()

  // 申请人：成了“管理”成员，可以看到加入申请与邀请链接，危险操作锁定
  await page.goto('/p/e2e-admin/m98-lab/settings')
  await expect(page.getByTestId('ps-requests')).toBeVisible()
  await expect(page.getByTestId('ps-invites')).toBeVisible()
  await expect(page.getByTestId('ps-manage-note')).toBeVisible()
  await expect(page.getByTestId('ps-delete')).toBeDisabled()
  await expect(page.getByTestId('ps-transfer')).toBeDisabled()
  expect(errors).toEqual([])
})

test('邀请链接：新建后只显示一次，打开链接直接加入；撤销后失效', async ({ page, browser }) => {
  const errors = collectErrors(page)
  const r = await admin.post('/api/v1/projects', { data: { name: 'M98 邀请', slug: 'm98-inv' } })
  expect(r.ok() || r.status() === 409, await r.text()).toBeTruthy()
  await login(page, 'pt-BR', ADMIN)
  await page.goto('/p/m98-inv/settings')
  await page.getByTestId('inv-new').click()
  await page.getByTestId('inv-role').locator('[data-role="edit"]').click()
  await page.getByTestId('inv-create').click()
  const url = await page.getByTestId('invite-url').inputValue()
  expect(url).toMatch(/\/invite\/lmi_/)

  const who = await newUser('m98-invitee')
  const ip = await (await browser.newContext()).newPage()
  await login(ip, 'zh-CN', who)
  await ip.goto(url)
  await expect(ip.getByTestId('invite-card')).toContainText('M98 邀请')
  await ip.getByTestId('invite-go').click()
  await expect(ip).toHaveURL(/\/p\/e2e-admin\/m98-inv\/devices/)
  await ip.goto(url)
  await expect(ip.getByTestId('invite-member')).toBeVisible()

  // 撤销后再打开：失效说明
  await page.reload()
  const rowRevoke = page.locator('[data-testid^="inv-revoke-"]').first()
  await rowRevoke.click()
  await expect(page.locator('[data-testid^="inv-revoke-"]')).toHaveCount(0)
  const other = await newUser('m98-late')
  const lp = await (await browser.newContext()).newPage()
  await login(lp, 'zh-CN', other)
  await lp.goto(url)
  await expect(lp.getByTestId('invite-dead')).toBeVisible()
  await ip.context().close()
  await lp.context().close()
  expect(errors).toEqual([])
})

async function darkBg(page: Page, testid: string): Promise<string> {
  return page.getByTestId(testid).evaluate((el) => getComputedStyle(el).backgroundColor)
}

test('暗色主题：等人邀请的提示与发现项目的列表不是白底', async ({ page }) => {
  const who = await newUser('m98-dark')
  await page.addInitScript(() => { localStorage.setItem('lmesh-theme', 'dark') })
  await login(page, 'zh-CN', who)
  await page.request.put('/api/v1/me/prefs', { data: { theme: 'dark' } })
  await page.goto('/projects')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  expect(await darkBg(page, 'projects-wait')).not.toBe('rgb(255, 255, 255)')
  await page.goto('/discover')
  expect(await darkBg(page, 'discover-list')).not.toBe('rgb(255, 255, 255)')
})
