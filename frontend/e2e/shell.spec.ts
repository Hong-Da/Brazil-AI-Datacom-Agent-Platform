import { expect, test } from '@playwright/test'
import { ADMIN, collectErrors, expectNoRawKeys, login } from './helpers'

const PAGES = ['dashboard', 'devices', 'device-graph', 'unknown-lines', 'schema-view', 'schema-edit', 'profiles', 'coverage', 'review', 'ingest', 'releases', 'ai-settings', 'users']

test('没登录时进入登录页，登录后回到原页面', async ({ page }) => {
  await page.goto('/profiles')
  await expect(page).toHaveURL(/\/login/)
  await page.getByTestId('login-username').fill(ADMIN.username)
  await page.getByTestId('login-password').fill(ADMIN.password)
  await page.getByTestId('login').click()
  await expect(page).toHaveURL(/\/profiles/)
})

test('导航到每个页面都能打开，没有脚本错误和未翻译的文案', async ({ page }) => {
  await login(page)
  const errors = collectErrors(page)
  await page.goto('/')
  for (const name of PAGES) {
    // 较慢的机器上，上一页还在加载时点击可能被吞掉：没跳转就再点一次
    await expect(async () => {
      await page.getByTestId(`nav-${name}`).click()
      await expect(page.getByTestId(`nav-${name}`)).toHaveAttribute('aria-current', 'page', { timeout: 4000 })
    }).toPass({ timeout: 20_000 })
    await expect(page.locator('main h1').first()).toBeVisible()
    await page.waitForLoadState('networkidle')
    await expectNoRawKeys(page)
  }
  expect(errors).toEqual([])
})

test('切换语言与主题', async ({ page }) => {
  await login(page)
  await page.goto('/')
  await page.getByTestId('lang-switch').selectOption('en')
  await expect(page.getByTestId('nav-devices')).toContainText('Devices')
  await page.getByTestId('lang-switch').selectOption('pt-BR')
  await expect(page.getByTestId('nav-devices')).toContainText('Dispositivos')
  await page.getByTestId('theme-switch').getByRole('button').nth(2).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await page.getByTestId('theme-switch').getByRole('button').nth(1).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
})

test('外壳显示知识库版本与计数', async ({ page }) => {
  await login(page)
  await page.goto('/')
  await expect(page.getByTestId('kb-chip')).toContainText('KB')
  await expect(page.getByTestId('nav-review').locator('.count')).toBeVisible()
})
