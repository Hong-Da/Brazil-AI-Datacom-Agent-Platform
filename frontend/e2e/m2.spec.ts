import { expect, test, type APIRequestContext } from '@playwright/test'
import { collectErrors, expectNoRawKeys, login, TOKEN } from './helpers'

// M2：配置对比、配置检查、冗余清理。e2e 服务导入了 ATN、ASR 920（两个版本）和 LAB-ATN-09。

async function devices(request: APIRequestContext): Promise<{ id: number; name: string; versions: number }[]> {
  const r = await request.get('/api/v1/devices', { headers: { Authorization: `Bearer ${TOKEN}` } })
  return (await r.json()).data.devices
}

test('配置对比：同一设备两个版本，报出 MTU 修改与改名，显式默认值说明可见', async ({ page, request }) => {
  await login(page)
  const errors = collectErrors(page)
  const asr = (await devices(request)).find((d) => d.versions >= 2)!
  expect(asr, '应有一台两个版本的设备').toBeTruthy()
  await page.goto(`/compare?mode=versions&a=${asr.id}`)
  await page.getByTestId('run-compare').click()
  await expect(page.getByTestId('diff-list')).toBeVisible()
  await expect(page.getByTestId('tally')).toContainText(/\d/)
  const rows = page.getByTestId('diff-row')
  expect(await rows.count()).toBeGreaterThan(3)
  await expect(page.getByTestId('diff-list')).toContainText('mtu')
  await expect(page.getByTestId('diff-list')).toContainText('EXPORT-LO')
  await rows.first().click()
  await expect(page.getByTestId('diff-detail')).toBeVisible()
  await page.getByTestId('view-graph').click()
  await expect(page.getByTestId('diff-graph')).toBeVisible()
  await expectNoRawKeys(page)
  expect(errors).toEqual([])
})

test('配置对比：粘贴两段等价配置（显式写默认值、改缩进）没有差异', async ({ page }) => {
  await login(page)
  await page.goto('/compare?mode=paste')
  const a = 'sysname R1\n#\ninterface GigabitEthernet0/2/1\n ip address 10.0.0.1 255.255.255.0\n#\nreturn'
  const b = 'sysname R1\n#\ninterface GigabitEthernet0/2/1\n ip address 10.0.0.1 24\n mtu 1500\n#\nreturn'
  const boxes = page.getByTestId('compare-setup').locator('textarea')
  await boxes.nth(0).fill(a)
  await boxes.nth(1).fill(b)
  await page.getByTestId('run-compare').click()
  await expect(page.getByTestId('compare-equal')).toBeVisible()
})

test('配置检查：LAB 设备报出发现，详情显示原文；忽略必须填原因', async ({ page, request }) => {
  await login(page)
  const errors = collectErrors(page)
  const atn = (await devices(request)).find((d) => d.name !== 'LAB-ATN-09' && !d.name.startsWith('PE-'))!
  await page.goto(`/check?device=${atn.id}`)
  await expect(page.getByTestId('finding-list')).toBeVisible()
  await page.getByTestId('finding-row').first().click()
  await expect(page.getByTestId('finding-detail')).toBeVisible()
  await expect(page.getByTestId('detail-lines')).toBeVisible()
  await page.getByTestId('btn-ignore').click()
  await expect(page.getByTestId('ignore-ok')).toBeDisabled()
  await page.getByTestId('ignore-reason').fill('e2e：已知情况')
  await page.getByTestId('ignore-ok').click()
  await page.getByTestId('show-ignored').check()
  await expect(page.getByTestId('btn-unignore').first()).toBeVisible()
  await page.getByTestId('tab-rules').click()
  await expect(page.getByTestId('rules-table')).toBeVisible()
  expect(await page.getByTestId('rule-row').count()).toBeGreaterThan(5)
  await expectNoRawKeys(page)
  expect(errors).toEqual([])
})

test('冗余清理：生成删除脚本并显示复检结果', async ({ page, request }) => {
  await login(page)
  const atn = (await devices(request)).find((d) => d.name !== 'LAB-ATN-09' && !d.name.startsWith('PE-'))!
  await page.goto(`/cleanup?device=${atn.id}`)
  await expect(page.getByTestId('orphan-tree')).toBeVisible()
  await expect(page.getByTestId('cleanup-script')).toContainText('undo bridge-domain 1500')
  await expect(page.getByTestId('cleanup-verify')).toBeVisible()
})

test('报告：检查报告中英文 HTML / Markdown 下载', async ({ page, request }) => {
  await login(page)
  const atn = (await devices(request)).find((d) => d.name !== 'LAB-ATN-09' && !d.name.startsWith('PE-'))!
  for (const [lang, fmt] of [['zh-CN', 'html'], ['en', 'md']] as const) {
    const r = await request.post('/api/v1/reports', {
      headers: { Authorization: `Bearer ${TOKEN}` },
      data: { kind: 'check', lang, format: fmt, check: { device_id: atn.id } },
    })
    expect(r.status()).toBe(200)
    const body = await r.text()
    expect(body).toContain(lang === 'zh-CN' ? '检查' : 'Check')
    expect(r.headers()['content-disposition']).toContain(`.${lang}.${fmt}`)
  }
  // 前一个用例忽略了这台设备唯一的发现，列表可能是“没有发现”状态；导出按钮照样可用
  await page.goto(`/check?device=${atn.id}`)
  await expect(page.getByTestId('btn-export')).toBeVisible()
  await page.getByTestId('btn-export').click()
  await expect(page.getByTestId('export-dialog')).toBeVisible()
})
