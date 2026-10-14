import { test, expect } from '@playwright/test'

test('真实槽位语义、多箱滚动、三队、分页与详情键盘桥', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/api/pets?*', async route => {
    const data = await (await route.fetch()).json(), template = data.pets[0]
    data.pets = Array.from({ length: 130 }, (_, index) => ({ ...template, gid: 10000 + index,
      name: '合成精灵 ' + index, location: null }))
    data.total = 131; data.shown = 130; data.version++
    const empty = () => ({ gid: 0, state: 'empty' })
    data.backpack.boxes = Array.from({ length: 36 }, (_, index) => ({ box_id: index + 1,
      name: '合成箱 ' + (index + 1), historical: index === 0, matched: index === 0 ? 2 : 1,
      occupied: index === 0 ? 4 : 1, unknown: index === 0 ? 1 : 0,
      slots: [{ gid: 10000 + index * 3, state: 'matched' }, ...Array.from({ length: 29 }, empty)] }))
    data.backpack.boxes[0].slots.splice(1, 4, { gid: 777777, state: 'filtered' },
      { gid: 10002, state: 'matched' }, { gid: 888888, state: 'missing' }, { gid: null, state: 'unknown' })
    data.backpack.teams = Array.from({ length: 3 }, (_, index) => ({ team_id: index + 1,
      name: '合成队伍', historical: true, matched: index < 2 ? 6 : 0,
      slots: Array.from({ length: 6 }, (_, slot) => index < 2 ? { gid: 10110 + index * 6 + slot, state: 'matched' } : empty()) }))
    data.backpack.active_team = 1; data.backpack.filtering = true
    data.backpack.unlocated_shown = 106; data.backpack.unlocated_total = 106
    await route.fulfill({ json: data })
  })
  await page.goto(process.env.SPRITELENS_DEMO_URL!)
  await expect(page.locator('#app')).toBeVisible()
  await page.locator('[data-page="pets"]').click()
  await expect(page.locator('#pet-count')).toHaveText('命中 130 / 131 只')
  await page.locator('#pet-view [data-view="point"]').click()
  await expect(page.locator('#pet-grid [data-slot]')).toHaveCount(30)
  await expect(page.locator('#pet-grid .slot-filtered')).toHaveText('筛掉')
  await expect(page.locator('#pet-grid .slot-missing')).toHaveText('待补')
  await expect(page.locator('#pet-grid .slot-unknown')).toHaveText('未采集')
  await expect(page.locator('#pet-box-navigation .box-number').first()).toHaveAttribute('title', /历史箱表/)
  const first = page.locator('#pet-grid button[data-slot="1"]'), third = page.locator('#pet-grid button[data-slot="3"]')
  await first.focus(); await first.press('ArrowRight'); await expect(third).toBeFocused()
  await third.press('Enter')
  await expect(page.locator('#pet-detail')).toBeVisible()
  await expect(page.locator('#pet-detail')).toContainText('合成精灵 2')
  await page.keyboard.press('Escape'); await expect(third).toBeFocused()
  await expect(page.locator('#pet-box-navigation .box-number')).toHaveCount(36)
  await page.locator('.box-tab-strip').hover(); await page.mouse.wheel(0, 700)
  await expect.poll(() => page.locator('.box-tab-strip').evaluate(node => node.scrollLeft)).toBeGreaterThan(0)
  await page.locator('#pet-box-navigation button[data-box="36"]').click()
  await expect(page.locator('#pet-box-navigation .box-number.active')).toHaveAttribute('data-box', '36')
  await page.locator('#pet-box-navigation button[data-box="0"]').click()
  await expect(page.locator('#pet-grid [data-slot]')).toHaveCount(18)
  await expect(page.locator('#pet-grid .pet-team-heading')).toHaveCount(3)
  await expect(page.locator('#pet-box-navigation button[data-box="0"]')).toContainText('出战')
  await page.locator('#pet-view [data-view="card"]').click()
  await expect(page.locator('#pet-grid .point-pet')).toHaveCount(30)
  await page.locator('#pet-page-navigation button[data-page="5"]').click()
  await expect(page.locator('#pet-grid .point-pet')).toHaveCount(10)
  expect(errors).toEqual([])
})

test('列表错误保留可见重试入口，错误槽位不能提交', async ({ page }) => {
  await page.goto(process.env.SPRITELENS_DEMO_URL!)
  await expect(page.locator('#app')).toBeVisible()
  await page.route('**/api/pets?*', route => route.fulfill({ status: 500, json: { error: '合成加载失败' } }))
  await page.locator('[data-page="pets"]').click()
  await expect(page.locator('#pet-empty-copy')).toContainText('合成加载失败')
  await expect(page.locator('#btn-pets-retry')).toBeVisible()
  await page.unroute('**/api/pets?*')
  await page.route('**/api/pets?*', async route => {
    const data = await (await route.fetch()).json()
    data.backpack.boxes[0].slots[0] = { gid: 999999, state: 'matched' }
    await route.fulfill({ json: data })
  })
  await page.locator('#btn-pets-retry').click()
  await expect(page.locator('#pet-empty-copy')).toContainText('列表与箱位数据不一致')
  await page.unroute('**/api/pets?*')
  await page.locator('#btn-pets-retry').click()
  await expect(page.locator('#pet-count')).toContainText('命中 40 / 40')
  await expect(page.locator('#btn-pets-retry')).toHaveCount(0)
  await page.locator('#pet-view [data-view="card"]').click()
  // 定位断言需要箱内个体：默认按图鉴 ID 排序后首卡可能是出战个体（无箱位）。
  // 逐页找到箱内的护主犬（gid 1025 起，不做出战个体），再验证定位。
  let card = page.locator('#pet-grid .point-pet').filter({ hasText: '护主犬' }).first()
  for (let page_ = 1; page_ < 5 && !(await card.isVisible()); page_ += 1) {
    await page.locator('#pet-page-navigation button[data-page="' + (page_ + 1) + '"]').click()
    await page.waitForTimeout(150)
  }
  const gid = await card.getAttribute('data-gid')
  await card.click()
  await page.locator('#pet-detail [data-locate-team], #pet-detail [data-locate-box]').click()
  await expect(page.locator('#pet-view [data-view="point"]')).toHaveAttribute('aria-pressed', 'true')
  await expect(page.locator(`#pet-grid [data-gid="${gid}"]`)).toBeFocused()
})

test('切号后新列表不会被取消无效的旧响应覆盖', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.addInitScript(() => {
    const Original = window.WebSocket
    window.WebSocket = class extends Original {
      constructor(url: string | URL, protocols?: string | string[]) {
        super(url, protocols)
        ;(window as unknown as { accountSocket: WebSocket }).accountSocket = this
      }
    }
    const original = window.fetch
    window.fetch = (input, options) => original(input,
      String(input).startsWith('/api/pets') ? { ...options, signal: undefined } : options)
  })
  await page.goto(process.env.SPRITELENS_DEMO_URL!)
  await expect(page.locator('#app')).toBeVisible()
  await page.locator('[data-page="pets"]').click()
  await expect(page.locator('#pet-count')).toContainText('命中 40 / 40')
  await page.locator('#pet-view [data-view="point"]').click()
  let requests = 0, releaseOld!: () => void
  await page.route('**/api/pets?*', async route => {
    const data = await (await route.fetch()).json()
    if (++requests === 1) await new Promise<void>(done => { releaseOld = done })
    else { data.uid = 202; data.version += 20; data.pets.forEach((pet: { name: string }) => { pet.name = '账号 B 精灵' }) }
    await route.fulfill({ json: data })
  })
  await page.locator('[data-page="pets"]').click()
  await expect.poll(() => Boolean(releaseOld)).toBe(true)
  await page.evaluate(async () => {
    const token = sessionStorage.getItem('spritelens.localToken') || ''
    const data = await (await fetch('/api/state', { headers: { 'X-Local-Token': token } })).json()
    data.uid = 202
    for (const key of ['pets_version', 'egg_box_version', 'home_version', 'flower_version']) data[key] += 20
    ;(window as unknown as { accountSocket: WebSocket }).accountSocket.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(data) }))
  })
  await expect(page.locator('#pet-grid')).toContainText('账号 B 精灵')
  const arrived = page.waitForResponse(response => new URL(response.url()).pathname === '/api/pets')
  releaseOld(); await (await arrived).finished()
  await expect(page.locator('#pet-grid')).toContainText('账号 B 精灵')
  await expect(page.locator('#pet-grid')).not.toContainText('迪莫')
  expect(errors).toEqual([])
})
