import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { expect, test } from '@playwright/test'
import { collectErrors, login, TOKEN, USER } from './helpers'

// REQ-038 删除设备与单个配置版本：用 API 导入一台有两个版本的设备 → 普通用户在版本历史里删除一个版本 → 在设备列表里删除设备。
// 用例自己导入、自己删除，不改变其他用例看到的设备名单。

const BASE = readFileSync(fileURLToPath(new URL('../../knowledge/samples/change/atn-base.cfg', import.meta.url)), 'utf-8')
  .replace('sysname ATN-CHANGE-01', 'sysname E2E-DEL-01')
const AUTH = { Authorization: `Bearer ${TOKEN}` }
const NAME = 'E2E-DEL-01'

test('删除设备与配置版本：版本历史删除一个版本 → 设备列表删除设备', async ({ page, request }) => {
  test.setTimeout(120_000)
  for (const [file, text] of [['del-v1.cfg', BASE], ['del-v2.cfg', BASE.replace(' mtu 9000', ' mtu 9216')]]) {
    const r = await request.post('/api/v1/configs', {
      headers: AUTH,
      multipart: { level: 'basic', files: { name: file, mimeType: 'text/plain', buffer: Buffer.from(text) } },
    })
    expect(r.ok(), await r.text()).toBeTruthy()
  }
  const devs = (await (await request.get('/api/v1/devices', { headers: AUTH })).json()).data.devices as { id: number; name: string; versions: number }[]
  const dev = devs.find((d) => d.name === NAME)!
  expect(dev.versions).toBe(2)
  const n0 = devs.length

  try {
    await login(page, 'zh-CN', USER) // 普通用户也可以删除
    const errors = collectErrors(page)

    // 版本历史：删除最新版本（#2）
    await page.goto(`/history/${dev.id}`)
    await expect(page.getByTestId('hist-meta')).toContainText('2')
    await page.getByTestId('hist-list-btn').click()
    await page.getByTestId('hist-del-2').click()
    const modal = page.getByTestId('devdel-modal')
    await expect(modal).toBeVisible()
    await expect(modal).toContainText(`删除版本：${NAME} #2`)
    await expect(modal.getByTestId('devdel-impact')).toContainText('其他版本（保留）')
    await modal.getByTestId('devdel-ok').click()
    await expect(modal).toBeHidden()
    await expect(page.locator('.m5-toast')).toContainText('已删除版本 #2')
    await expect(page.getByTestId('hist-single')).toBeVisible()
    // 只剩一个版本：删除按钮不可用
    await expect(page.getByTestId('hist-card-del-only')).toBeDisabled()

    // 设备列表：删除设备（确认框列出连带删除的内容），暗色主题下对话框不是白底
    await page.emulateMedia({ colorScheme: 'dark' })
    await page.goto('/devices')
    const table = page.getByTestId('devices-table')
    await expect(table.getByTestId('device-link')).toHaveCount(n0)
    const row = table.locator('tr', { has: page.getByText(NAME, { exact: true }) })
    await row.getByTestId('device-delete').click()
    await expect(modal).toContainText(`删除设备：${NAME}`)
    await expect(modal.getByTestId('devdel-impact')).toContainText('配置版本（含快照）')
    await expect(modal.getByTestId('devdel-impact')).toContainText('导入记录')
    const bg = await modal.locator('.modal').evaluate((el) => getComputedStyle(el).backgroundColor)
    expect(bg).not.toBe('rgb(255, 255, 255)')
    await modal.getByTestId('devdel-ok').click()
    await expect(modal).toBeHidden()
    await expect(page.getByTestId('device-deleted')).toContainText(`已删除设备 ${NAME}`)
    await expect(table.getByTestId('device-link')).toHaveCount(n0 - 1)
    await expect(table).not.toContainText(NAME)
    expect(errors).toEqual([])
  } finally {
    // 失败时也清理（已删除时返回 404，忽略）
    await request.delete(`/api/v1/devices/${dev.id}?force=true`, { headers: AUTH })
  }
})
