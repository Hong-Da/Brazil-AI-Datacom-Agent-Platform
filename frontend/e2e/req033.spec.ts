import { expect, test, type Page } from '@playwright/test'
import { collectErrors, login, USER } from './helpers'

// REQ-033 内置 AI skill（e2e 服务不配置 AI）：管理员打开列表 → 进入 ask-query → 编辑提示词保存为 v1 →
// 恢复内置 / 回滚到 v1；未配置 AI 时进化不可用、试运行只能回放；普通用户看不到入口、直接打开回到首页。

async function expectNoKeys(page: Page): Promise<void> {
  const text = await page.locator('main').innerText()
  const raw = text.match(/\bai-skills\.[a-zA-Z][\w.-]*\b/g)
  expect(raw ?? [], `未翻译的文案键：${raw?.join(', ')}`).toEqual([])
}
const active = (page: Page) => page.locator('.h1row [data-ver]')

test('AI skill：列表、编辑保存为新版本、回滚与恢复内置、未配置 AI 时的限制', async ({ page }) => {
  test.setTimeout(120_000)
  await login(page)
  const errors = collectErrors(page)

  // 导航入口在“系统”组
  await page.goto('/')
  await page.getByTestId('nav-ai-skills').click()
  await expect(page).toHaveURL(/\/ai-skills$/)
  await expect(page.getByTestId('sk-row')).toHaveCount(25) // 原有 6 个 + M8 新增 18 个（日常分析 6、变更与割接 5、规范与合规 3、知识库 3、报告 1）+ 会话报告 ask-report（REQ-054）
  // 按功能分组（REQ-033 评审修改）：问答组 3 个；按组筛选、跨组搜索、折叠
  await expect(page.locator('[data-group="qa"] [data-testid="sk-row"]')).toHaveCount(3)
  await page.getByTestId('sk-group-kb').click()
  await expect(page.getByTestId('sk-row')).toHaveCount(4)
  await page.getByTestId('sk-group-all').click()
  await page.getByTestId('sk-filter').fill('ask-')
  await expect(page.getByTestId('sk-group-block')).toHaveCount(1)
  await page.getByTestId('sk-filter').fill('')
  await page.getByTestId('sk-group-toggle-qa').click()
  await expect(page.getByTestId('sk-row')).toHaveCount(22)
  await page.getByTestId('sk-group-toggle-qa').click()
  await expect(page.getByTestId('sk-ai-off')).toBeVisible()
  await expectNoKeys(page)

  // 进入 ask-query
  await page.getByTestId('sk-open-ask-query').click()
  await expect(page).toHaveURL(/\/ai-skills\/ask-query$/)
  await expect(page.getByTestId('sk-title')).toBeVisible()
  await expect(active(page)).toHaveAttribute('data-ver', 'builtin')
  await expectNoKeys(page)

  // 未登记的变量不能保存
  const prompt = page.getByTestId('pe-prompt').locator('textarea')
  const orig = await prompt.inputValue()
  await prompt.fill(`${orig}\n{nope}`)
  await expect(page.getByTestId('unk-var')).toBeVisible()
  await expect(page.getByTestId('def-save')).toBeDisabled()

  // 编辑提示词，保存为新版本 → v1 生效
  await prompt.fill(`${orig}\nBe brief.`)
  await page.getByTestId('save-note').fill('e2e：回答更简短')
  await expect(page.getByTestId('def-save')).toBeEnabled()
  await page.getByTestId('def-save').click()
  await expect(page.getByTestId('sk-toast')).toContainText('v1')
  await expect(active(page)).toHaveAttribute('data-ver', '1')
  await expect(page.getByTestId('def-save')).toBeDisabled()

  // 未配置 AI：进化不可用并说明原因
  await expect(page.getByTestId('sk-go-evolve')).toBeDisabled()
  await expect(page.getByTestId('sk-evo-why')).not.toBeEmpty()

  // 试运行只能回放
  await page.getByTestId('sk-tab-test').click()
  await expect(page.getByTestId('test-mode-ai')).toBeDisabled()
  await expect(page.getByTestId('test-mode-replay')).toHaveAttribute('aria-pressed', 'true')
  await page.getByTestId('test-run').click()
  await expect(page.getByTestId('test-replay-flag')).toBeVisible()
  await expect(page.getByTestId('test-checks')).toBeVisible()

  // 版本历史：内置 + v1，逐字段对比
  await page.getByTestId('sk-tab-versions').click()
  await expect(page.getByTestId('ver-item')).toHaveCount(2)
  await expect(page.locator('[data-testid="diff-field"][data-field="prompt"] .cnt')).toContainText('+1')
  // 恢复内置
  await page.getByTestId('ver-restore').click()
  await page.getByTestId('ver-confirm-ok').click()
  await expect(active(page)).toHaveAttribute('data-ver', 'builtin')
  await expect(page.locator('[data-testid="ver-item"][data-version="builtin"] [data-testid="ver-active"]')).toBeVisible()
  // 回滚到 v1（不新增版本记录）
  await page.getByTestId('ver-rollback').click()
  await page.getByTestId('ver-confirm-ok').click()
  await expect(active(page)).toHaveAttribute('data-ver', '1')
  await expect(page.getByTestId('ver-item')).toHaveCount(2)

  // 进化页：开始按钮不可用
  await page.getByTestId('sk-tab-evolve').click()
  await expect(page.getByTestId('evo-start')).toBeDisabled()
  await expect(page.getByTestId('evo-ai-off')).toBeVisible()
  await expectNoKeys(page)

  // 收尾：恢复内置，便于重复运行
  await page.getByTestId('sk-tab-versions').click()
  await page.getByTestId('ver-restore').click()
  await page.getByTestId('ver-confirm-ok').click()
  await expect(active(page)).toHaveAttribute('data-ver', 'builtin')
  expect(errors).toEqual([])
})

test('AI skill：普通用户看不到入口，直接打开回到首页', async ({ page }) => {
  await login(page, 'zh-CN', USER)
  await page.goto('/')
  await expect(page.getByTestId('nav-dashboard')).toBeVisible()
  await expect(page.getByTestId('nav-ai-skills')).toHaveCount(0)
  await page.goto('/ai-skills')
  await expect(page).toHaveURL(/\/$/)
  await page.goto('/ai-skills/ask-query')
  await expect(page).toHaveURL(/\/$/)
})
