import { test, expect } from '@playwright/test'

test.beforeEach(async ({ page }) => {
  // 阻断外网，证明页面与资源可离线加载。
  await page.route('**/*', route => new URL(route.request().url()).hostname === '127.0.0.1'
    ? route.continue() : route.abort())
  await page.goto(process.env.SPRITELENS_DEMO_URL!)
  await expect(page.locator('.boot-mask')).toHaveCount(0)
  await page.locator('[data-page="egg-dex"]').click()
  await expect(page.locator('#ed-grid .hb-card').first()).toBeVisible()
})

test('筛选、空态、错误重试、切页返回与精度契约', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.locator('#ed-search').fill('不存在的合成蛋')
  await expect(page.locator('#page-egg-dex .empty-hint')).toContainText('没有符合筛选条件的蛋')
  await page.getByRole('button', { name: '清除筛选', exact: true }).first().click()
  await expect(page.locator('#ed-grid .hb-card').first()).toBeVisible()
  await page.locator('#ed-group').selectOption({ index: 1 })
  await expect(page.locator('#ed-grid .hb-card').first()).toBeVisible()
  await page.locator('#ed-type').selectOption({ index: 1 })
  await page.locator('#ed-hatch').selectOption('12')
  await expect(page.locator('#ed-grid .hb-card').first()).toBeVisible()
  const times = await page.locator('#ed-grid .hb-badge').allTextContents()
  expect(times.length).toBeGreaterThan(0)
  expect(times.every(label => Number.parseFloat(label.replace(/[^\d.]/g, '')) >= 12)).toBe(true)
  await page.route('**/api/eggs?*', route => route.fulfill({ status: 500, json: { message: '合成读取失败' } }))
  await page.locator('#ed-group').selectOption('')
  await expect(page.getByRole('alert')).toContainText('合成读取失败')
  await page.unroute('**/api/eggs?*')
  await page.getByRole('button', { name: '重试', exact: true }).click()
  await expect(page.locator('#ed-grid .hb-card').first()).toBeVisible()
  for (let i = 0; i < 3; i++) {
    await page.locator('[data-page="overview"]').click()
    await page.locator('[data-page="egg-dex"]').click()
    await expect(page.locator('#ed-grid .hb-card').first()).toBeVisible()
    expect(await page.locator('#ed-grid').count()).toBe(1)
  }
  const ids = await page.evaluate(async () => {
    const token = sessionStorage.getItem('spritelens.localToken') || ''
    const response = await fetch('/api/home', { headers: { 'X-Local-Token': token } })
    const data = await response.json()
    return data.residents.map((r: { actor_id: unknown }) => r.actor_id)
  })
  expect(ids).toContain('9518406239959121930')
  expect(ids).toContain('9518406239959121931')
  const bootstrap = await page.evaluate(async () => {
    const token = sessionStorage.getItem('spritelens.localToken') || ''
    const response = await fetch('/api/bootstrap', { headers: { 'X-Local-Token': token } })
    return response.json()
  })
  expect(bootstrap.pets.uid).toBe(bootstrap.overview.uid)
  expect(bootstrap.state.uid).toBe(bootstrap.overview.uid)
  expect(bootstrap.pets.version).toBe(bootstrap.overview.version)
  expect(bootstrap.state.pets_version).toBe(bootstrap.overview.version)
  expect(bootstrap.pets.total).toBe(bootstrap.overview.stats.total)
  expect(bootstrap.state.pets_total).toBe(bootstrap.overview.stats.total)
  expect(errors).toEqual([])
})

for (const width of [1440, 1280, 960, 640]) {
  test(`主题、键盘和焦点 ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    for (const theme of ['miaomiao', 'huohua', 'shuilanlan']) {
      await page.evaluate(value => { document.documentElement.dataset.theme = value }, theme)
      const card = page.locator('#ed-grid .hb-card').first()
      await card.focus()
      await card.press('Enter')
      const detail = page.locator('#ed-detail')
      await expect(detail).toBeVisible()
      await expect(detail.getByRole('button', { name: '关闭详情' })).toBeFocused()
      if (width <= 1360) {
        await expect(detail).toHaveAttribute('role', 'dialog')
        await page.keyboard.press('Tab')
        await expect(detail.getByRole('button', { name: '关闭详情' })).toBeFocused()
      }
      await page.screenshot({ path: `test-results/egg-dex-${width}-${theme}.png` })
      const box = await detail.boundingBox()
      expect(box && box.x >= 0 && box.x + box.width <= width + 1).toBeTruthy()
      await page.keyboard.press('Escape')
      await expect(detail).toHaveCount(0)
      await expect(card).toBeFocused()
    }
  })
}
