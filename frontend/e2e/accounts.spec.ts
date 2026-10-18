import { expect, test, type Page } from '@playwright/test'
import { ADMIN, collectErrors, USER } from './helpers'

/** 用户账号（REQ-030）：登录 → 账号管理 → 普通用户登录看不到管理员入口 → 登出。 */

async function signIn(page: Page, who: { username: string; password: string }): Promise<void> {
  await page.goto('/login')
  await page.getByTestId('login-username').fill(who.username)
  await page.getByTestId('login-password').fill(who.password)
  await page.getByTestId('login').click()
  await expect(page).toHaveURL(/\/$/)
}

async function signOut(page: Page): Promise<void> {
  await page.getByTestId('user-menu-button').click()
  await page.getByTestId('menu-logout').click()
  await expect(page).toHaveURL(/\/login/)
}

test('密码错误时提示，不跳转', async ({ page }) => {
  await page.goto('/login')
  await page.getByTestId('login-username').fill(USER.username)
  await page.getByTestId('login-password').fill('wrong-password')
  await page.getByTestId('login').click()
  await expect(page.getByTestId('login-error')).toBeVisible()
  await expect(page).toHaveURL(/\/login/)
})

test('管理员登录 → 新建账号 → 登出；普通用户看不到管理员入口', async ({ page }) => {
  const errors = collectErrors(page)
  await signIn(page, ADMIN)
  await expect(page.getByTestId('user-menu')).toContainText(ADMIN.username)
  await expect(page.getByTestId('nav-users')).toBeVisible()

  // 账号管理：列表里有两个预置账号；自己的账号不能停用或删除
  await page.getByTestId('nav-users').click()
  await expect(page.getByTestId('users-table')).toBeVisible()
  await expect(page.getByTestId(`user-row-${USER.username}`)).toBeVisible()
  await expect(page.getByTestId(`user-row-${ADMIN.username}`).getByTestId('user-delete')).toBeDisabled()

  // 新建一个普通账号
  await page.getByTestId('users-new').click()
  await page.getByTestId('new-username').fill('e2e-temp')
  await page.getByTestId('new-password').fill('Temp-pass-123')
  await page.getByTestId('users-dialog-ok').click()
  await expect(page.getByTestId('user-row-e2e-temp')).toBeVisible()
  // 删除它
  await page.getByTestId('user-row-e2e-temp').getByTestId('user-delete').click()
  await page.getByTestId('users-dialog-ok').click()
  await expect(page.getByTestId('user-row-e2e-temp')).toHaveCount(0)

  await signOut(page)

  // 普通用户：没有“系统”分组与账号管理菜单；直接打开管理员页面回到首页
  await signIn(page, USER)
  await expect(page.getByTestId('user-menu')).toContainText(USER.username)
  await expect(page.getByTestId('nav-devices')).toBeVisible()
  await expect(page.getByTestId('nav-users')).toHaveCount(0)
  await expect(page.getByTestId('nav-ai-settings')).toHaveCount(0)
  await page.getByTestId('user-menu-button').click()
  await expect(page.getByTestId('menu-password')).toBeVisible()
  await expect(page.getByTestId('menu-users')).toHaveCount(0)
  await page.keyboard.press('Escape')
  await page.goto('/users')
  await expect(page).toHaveURL(/\/$/)

  await signOut(page)
  // 登出后再打开页面要求登录
  await page.goto('/devices')
  await expect(page).toHaveURL(/\/login/)
  expect(errors.filter((e) => !/403|401/.test(e))).toEqual([])
})

test('会话失效时跳回登录页并说明原因', async ({ page, context }) => {
  await signIn(page, USER)
  await context.clearCookies()
  // 页面上任何一次请求返回 401 都会跳回登录页（外壳的计数刷新可能已经先触发了），这里再点一次导航确保有请求
  // 外壳的请求可能恰好在 evaluate 执行中返回 401 并跳转，页面上下文随之销毁：这正是要验证的结果，忽略该错误，其余错误照常抛出
  await page.evaluate(() => document.querySelector<HTMLElement>('[data-testid="nav-devices"]')?.click())
    .catch((e: Error) => { if (!/Execution context was destroyed/.test(e.message)) throw e })
  await expect(page).toHaveURL(/\/login\?.*expired=1/)
  await expect(page.getByTestId('login-expired')).toBeVisible()
})
