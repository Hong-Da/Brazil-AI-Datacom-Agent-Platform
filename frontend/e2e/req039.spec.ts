import { expect, request as pwRequest, test } from '@playwright/test'
import { ADMIN, collectErrors, login } from './helpers'

/**
 * REQ-039 用户自助注册：管理员开启注册（需审核）→ 新用户在登录页注册 → 待审核不能登录 →
 * 管理员在账号管理里批准 → 新用户登录后看到自己的默认项目。结束时关闭注册（恢复默认）。
 */
test('自助注册：开启、注册、待审核、批准、登录看到默认项目', async ({ page, browser, baseURL }) => {
  test.setTimeout(120_000)
  const name = `e2e-reg-${Date.now() % 100000}`
  const pw = 'E2e-reg-pass-1'
  const admin = await pwRequest.newContext({ baseURL })
  expect((await admin.post('/api/v1/auth/login', { data: ADMIN })).ok()).toBeTruthy()
  try {
    // 管理员在账号管理里开启注册（需要审核为默认）
    await login(page, 'zh-CN', ADMIN)
    const errors = collectErrors(page)
    await page.goto('/users')
    await expect(page.getByTestId('reg-panel')).toBeVisible()
    await expect(page.getByTestId('reg-state-closed')).toBeVisible()
    await page.getByTestId('reg-allow').locator('..').click() // 点开关（复选框本身不可见）
    await expect(page.getByTestId('reg-allow')).toBeChecked()
    await expect(page.getByTestId('reg-approval')).toBeChecked()
    await page.getByTestId('reg-rate').fill('1000') // 反复运行用例时不被频率限制挡住
    await page.getByTestId('reg-save').click()
    await expect(page.getByTestId('reg-state-open')).toBeVisible()
    expect(errors).toEqual([])

    // 新用户：登录页有注册入口 → 注册 → 等待审核
    const ctx = await browser.newContext()
    const np = await ctx.newPage()
    await np.addInitScript(() => { localStorage.setItem('lmesh-lang', 'zh-CN') })
    await np.goto('/login')
    await np.getByTestId('login-to-register').click()
    await expect(np).toHaveURL(/\/register$/)
    await np.getByTestId('register-username').fill(name)
    await np.getByTestId('register-password').fill(pw)
    await np.getByTestId('register-password2').fill(pw)
    await np.getByTestId('register-submit').click()
    await expect(np.getByTestId('register-pending')).toBeVisible()
    // 待审核：登录被拒并说明
    await np.getByTestId('register-back').click()
    await np.getByTestId('login-username').fill(name)
    await np.getByTestId('login-password').fill(pw)
    await np.getByTestId('login').click()
    await expect(np.getByTestId('login-pending')).toBeVisible()

    // 管理员批准
    await page.reload()
    await expect(page.getByTestId('users-pending-bar')).toBeVisible()
    await page.getByTestId('users-filter-pending').click()
    const row = page.getByTestId(`user-row-${name}`)
    await expect(row.getByTestId('user-origin-register')).toBeVisible()
    await row.getByTestId('user-approve').click()
    await expect(page.getByTestId('users-toast')).toBeVisible()

    // 批准后登录：看到自己的默认项目
    await np.getByTestId('login').click()
    await expect(np).toHaveURL(/\/$|\/upgrade$/)
    await np.goto('/projects')
    await expect(np.getByTestId('project-card-default')).toBeVisible()
    await expect(np.getByTestId('project-current')).toHaveText('默认项目')
    await ctx.close()

    // 关闭注册后：直接打开注册页说明“注册未开放”，登录页没有注册入口
    expect((await admin.put('/api/v1/auth/settings', { data: { registration: false } })).ok()).toBeTruthy()
    const ctx2 = await browser.newContext()
    const cp = await ctx2.newPage()
    await cp.goto('/register')
    await expect(cp.getByTestId('register-closed')).toBeVisible()
    await cp.goto('/login')
    await expect(cp.getByTestId('login-form')).toBeVisible()
    await expect(cp.getByTestId('login-register')).toHaveCount(0)
    await ctx2.close()
  } finally {
    await admin.put('/api/v1/auth/settings', { data: { registration: false, approval: true, rate_per_hour: 5 } })
    await admin.delete(`/api/v1/users/${name}?delete_projects=true`)
    await admin.dispose()
  }
})
