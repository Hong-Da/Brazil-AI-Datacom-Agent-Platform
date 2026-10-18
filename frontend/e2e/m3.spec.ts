import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { expect, test, type APIRequestContext } from '@playwright/test'
import { collectErrors, login, TOKEN } from './helpers'

// M3：配置翻译、配置模板、批量生成。e2e 服务导入了 ATN、ASR 920（两个版本）和 LAB-ATN-09。

const SAMPLE = fileURLToPath(new URL('../../knowledge/samples/cisco-iosxe-asr920-synthetic/pe-asr920-01.cfg', import.meta.url))

async function devices(request: APIRequestContext): Promise<{ id: number; name: string }[]> {
  const r = await request.get('/api/v1/devices', { headers: { Authorization: `Bearer ${TOKEN}` } })
  return (await r.json()).data.devices
}

/** 页面上不应出现 M3 页面未翻译的文案键 */
async function expectNoM3Keys(page: import('@playwright/test').Page): Promise<void> {
  const text = await page.locator('main').innerText()
  const raw = text.match(/\b(translate|templates|generate)\.[a-zA-Z][\w.]*\b/g)
  expect(raw ?? [], `未翻译的文案键：${raw?.join(', ')}`).toEqual([])
}

test('配置翻译：ASR 920 → ATN 出现告警与校验结果，告警与两侧原文联动', async ({ page, request }) => {
  await login(page)
  const errors = collectErrors(page)
  const asr = (await devices(request)).find((d) => d.name.startsWith('PE-ASR920'))!
  expect(asr, '应有 ASR 920 设备').toBeTruthy()
  await page.goto(`/translate?device=${asr.id}&to=huawei-atn-v800r025`)
  await expect(page.getByTestId('tr-target')).toHaveValue('huawei-atn-v800r025')
  await page.getByTestId('tr-run').click()
  await expect(page.getByTestId('tr-verify')).toBeVisible({ timeout: 60_000 })
  await expect(page.getByTestId('tr-verify')).toContainText(/一致|说明|差异/)
  await expect(page.getByTestId('tr-sum-default')).toBeVisible()
  const warns = page.getByTestId('tr-warn')
  expect(await warns.count()).toBeGreaterThan(3)
  // 默认值差异：译文中显式写出
  await page.getByTestId('tr-sum-default').click()
  await expect(page.getByTestId('tr-warns')).toContainText('per-instance')
  await page.getByTestId('tr-sum-default').click()
  // 未翻译的原文：选中后源配置对应行高亮
  await page.getByTestId('tr-tab-raw').click()
  await warns.first().click()
  await expect(page.locator('[data-testid="tr-src"] .l.linked').first()).toBeVisible()
  await expect(page.getByTestId('tr-out')).toContainText('LMESH untranslated')
  // 显示默认配置：译文改用含默认值的结果
  await page.getByTestId('tr-show-default').check()
  await expect(page.locator('[data-testid="tr-out"] .l.ghost-d').first()).toBeVisible({ timeout: 30_000 })
  await page.getByTestId('tr-show-default').uncheck()
  // 下载
  await page.getByTestId('tr-download').click()
  const dl = page.waitForEvent('download')
  await page.getByTestId('tr-dl-warn').click()
  expect((await dl).suggestedFilename()).toBe('warnings.csv')
  await expectNoM3Keys(page)
  expect(errors).toEqual([])
})

test('配置模板：校验合成样本报出缺失项，提取变量；正文高亮变量', async ({ page }) => {
  await login(page)
  const errors = collectErrors(page)
  await page.goto('/templates?id=cisco-asr920-efp-bdi-vrf')
  await expect(page.getByTestId('tpl-body')).toBeVisible()
  await expect(page.locator('[data-testid="tpl-body"] .vx').first()).toBeVisible()
  await expect(page.getByTestId('tpl-vars')).toContainText('uplink_net')
  await page.getByTestId('tpl-tab-check').click()
  await page.getByTestId('tpl-ck-paste').click()
  await page.getByTestId('tpl-ck-text').fill(readFileSync(SAMPLE, 'utf-8'))
  await page.getByTestId('tpl-ck-run').click()
  await expect(page.getByTestId('tpl-ck-verdict')).toBeVisible({ timeout: 60_000 })
  await expect(page.getByTestId('tpl-ck-verdict')).toContainText('不符合模板')
  await page.getByTestId('tpl-kf-missing').click()
  const missing = page.getByTestId('tpl-finding')
  expect(await missing.count()).toBeGreaterThan(0)
  await expect(missing.first()).toContainText('缺少')
  await missing.first().click()
  await expect(missing.first()).toContainText('模板第')
  await expect(page.getByTestId('tpl-xv')).toContainText('10.255.0.21')
  await page.getByTestId('tpl-tab-text').click()
  await page.getByTestId('tpl-view-yaml').click()
  await expect(page.locator('pre.yaml-ro')).toContainText('id: cisco-asr920-efp-bdi-vrf')
  await expectNoM3Keys(page)
  expect(errors).toEqual([])
})

test('批量生成：上传两行参数全部通过，可下载 ZIP；改坏一格后该行报错', async ({ page }) => {
  await login(page)
  const errors = collectErrors(page)
  await page.goto('/generate?template=cisco-asr920-efp-bdi-vrf')
  await expect(page.getByTestId('gen-grid')).toBeVisible()
  const csv = [
    'device,hostname,asn,loopback,uplink,uplink_net,access,access_desc,rr1,rr2,svc.vlan,svc.vrf,svc.rt,svc.desc,svc.lan',
    'PE-A,PE-A,64512,10.255.0.31,GigabitEthernet0/0/0,10.1.0.4/30,GigabitEthernet0/0/1,SITE-A,10.255.0.1,10.255.0.2,101;102,RAN-2G;MGMT,101;10,D1;D2,172.16.1.0/24;172.16.2.0/24',
    'PE-B,PE-B,64512,10.255.0.32,GigabitEthernet0/0/0,10.1.0.8/30,GigabitEthernet0/0/1,SITE-B,10.255.0.1,10.255.0.2,201,RAN-4G,201,D3,172.16.3.0/24',
  ].join('\n') + '\n'
  await page.getByTestId('gen-csv-input').setInputFiles({ name: 'params.csv', mimeType: 'text/csv', buffer: Buffer.from(csv) })
  await expect(page.getByTestId('gen-row')).toHaveCount(2)
  await expect(page.getByTestId('gen-ok')).toHaveText('2', { timeout: 60_000 })
  await expect(page.getByTestId('gen-bad')).toHaveText('0')
  await expect(page.getByTestId('gen-preview')).toContainText('hostname PE-A')
  await expect(page.locator('[data-testid="gen-stage-roundtrip"].ok')).toBeVisible()
  await page.getByTestId('gen-download').click()
  const dl = page.waitForEvent('download')
  await page.getByTestId('gen-zip').click()
  expect((await dl).suggestedFilename()).toMatch(/^generate-cisco-asr920-efp-bdi-vrf-.*\.zip$/)
  // loopback 不在 within 网段内：这一行报错，单元格标红
  await page.getByTestId('gen-cell-1-loopback').fill('10.9.0.32')
  await expect(page.getByTestId('gen-bad')).toHaveText('1', { timeout: 60_000 })
  await expect(page.getByTestId('gen-cell-1-loopback')).toHaveClass(/bad/)
  await expect(page.locator('[data-testid="gen-stage-params"].bad')).toBeVisible()
  await expectNoM3Keys(page)
  expect(errors).toEqual([])
})
