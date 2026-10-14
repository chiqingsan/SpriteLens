import { test, expect } from '@playwright/test'

test('定稿布局、UID隐私、双按钮筛选和详情共享栏', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.setViewportSize({ width: 1586, height: 992 })
  await page.goto(process.env.SPRITELENS_DEMO_URL!)
  await expect(page.locator('#app')).toBeVisible()
  await page.locator('[data-page="pets"]').click()
  await expect(page.locator('#pet-count')).toContainText('命中 40 / 40')
  await page.locator('#pet-view [data-view="point"]').click()
  await expect(page.locator('#capture-message')).toBeHidden()
  await page.getByRole('button', { name: '隐藏 UID', exact: true }).click()
  await expect(page.locator('#role-uid')).toContainText('••••••••')
  await page.getByRole('button', { name: '显示 UID', exact: true }).click()
  await expect(page.locator('#role-uid')).not.toContainText('••••••••')
  const grid = page.locator('#pet-grid'), rail = page.locator('#pet-filters')
  await expect(grid.locator('[data-slot]')).toHaveCount(30)
  expect(await grid.evaluate(node => getComputedStyle(node).gridTemplateColumns.split(' ').length)).toBe(6)
  await expect(rail.locator('input[type="checkbox"]')).toHaveCount(0)
  const offsets = await grid.locator('.point-pet').evaluateAll(nodes => nodes.map(node => {
    const card = node.getBoundingClientRect(), markers = node.querySelector('.point-markers')!.getBoundingClientRect()
    return Math.abs(markers.x + markers.width / 2 - card.x - card.width / 2)
  }))
  expect(offsets.every(value => value < 1)).toBe(true)
  console.log('双图标组距卡片中线的最大偏差(px):', Math.max(...offsets))
  const imageOffsets = await grid.locator('.point-markers').evaluateAll(nodes => nodes.flatMap(node => {
    return [...node.querySelectorAll('.point-rarity-slot, .point-color-slot')].flatMap(slot => {
      const icon = slot.firstElementChild
      if (!icon) return []
      const a = slot.getBoundingClientRect(), b = icon.getBoundingClientRect()
      return [Math.abs(a.x + a.width / 2 - b.x - b.width / 2), Math.abs(a.y + a.height / 2 - b.y - b.height / 2)]
    })
  }))
  expect(imageOffsets.every(value => value < 1)).toBe(true)
  const searchWidth = await page.locator('#f-search').evaluate(node => node.getBoundingClientRect().width)
  expect(searchWidth).toBeGreaterThanOrEqual(220); expect(searchWidth).toBeLessThanOrEqual(280)
  const width = await grid.evaluate(node => node.getBoundingClientRect().width)
  const sharedArea = await rail.boundingBox()
  expect(sharedArea!.width).toBe(360)
  await page.screenshot({ path: 'test-results/pet-layout-1586.png' })
  await grid.locator('.point-pet').first().click()
  await expect(page.locator('#pet-detail')).toBeVisible()
  await expect(rail).toBeHidden()
  expect(await page.locator('#pet-detail').boundingBox()).toEqual(sharedArea)
  expect(await grid.evaluate(node => node.getBoundingClientRect().width)).toBe(width)
  await page.screenshot({ path: 'test-results/pet-layout-shared-detail.png' })
  await page.keyboard.press('Escape')
  await expect(rail).toBeVisible()
  expect(await rail.boundingBox()).toEqual(sharedArea)
  const gender = rail.locator('#f-gender .chip').first()
  await gender.click(); await expect(gender).toHaveAttribute('aria-pressed', 'true')
  await gender.click(); await expect(gender).toHaveAttribute('aria-pressed', 'false')
  await expect(rail.locator('.condition-pool')).toHaveCount(0)
  const mode = page.locator('#pet-filter-actions .filter-match-mode')
  await expect(mode).toBeVisible()
  const response = page.waitForResponse(result => new URL(result.url()).pathname === '/api/pets' && new URL(result.url()).searchParams.get('shiny') === '1')
  await rail.locator('.direct-filter').first().getByRole('button', { name: '异色', exact: true }).click()
  const filtered = await (await response).json()
  expect(filtered.pets.every((pet: { is_shiny: boolean }) => pet.is_shiny)).toBe(true)
  const combinedResponse = page.waitForResponse(result => {
    const params = new URL(result.url()).searchParams
    return new URL(result.url()).pathname === '/api/pets' && params.get('shiny') === '1' && params.get('gender') === '1' && params.get('pool_mode') === 'and'
  })
  await gender.click()
  const combined = await (await combinedResponse).json()
  expect(combined.pets.every((pet: { is_shiny: boolean; gender: number }) => pet.is_shiny && pet.gender === 1)).toBe(true)
  const unionResponse = page.waitForResponse(result => new URL(result.url()).pathname === '/api/pets' && new URL(result.url()).searchParams.get('pool_mode') === 'or')
  await mode.locator('button').last().click()
  const union = await (await unionResponse).json()
  expect(union.shown).toBeGreaterThanOrEqual(combined.shown)
  expect(union.pets.every((pet: { is_shiny: boolean; gender: number }) => pet.is_shiny || pet.gender === 1)).toBe(true)
  await gender.click()
  for (const name of ['大块头', '小不点', '婉转声', '粗嗓门']) await rail.locator('.quick-filters').getByRole('button', { name, exact: true }).click()
  await expect(rail.locator('.quick-filters .chip.active')).toHaveCount(4)
  await page.screenshot({ path: 'test-results/pet-layout-conditions.png' })
  for (const name of ['大块头', '小不点', '婉转声', '粗嗓门']) await rail.locator('.quick-filters').getByRole('button', { name, exact: true }).click()
  await rail.locator('.direct-filter').first().getByRole('button', { name: '异色', exact: true }).click()
  await expect(rail.locator('.direct-filter').first().getByRole('button', { name: '异色', exact: true })).toHaveAttribute('aria-pressed', 'false')
  await mode.locator('button').last().click()
  await expect(mode.locator('button').last()).toHaveAttribute('aria-pressed', 'true')
  await page.locator('#btn-reset-filters').click()
  for (const viewport of [{ width: 1280, height: 900 }, { width: 640, height: 900 }]) {
    await page.setViewportSize(viewport)
    await page.screenshot({ path: `test-results/pet-layout-${viewport.width}.png` })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    if (viewport.width === 640) {
      await page.locator('.account-information summary').click()
      await expect(page.locator('#role-uid')).toBeVisible()
      await expect(page.locator('#role-name')).toBeVisible()
      await page.locator('#page-title').click()
      await expect(page.locator('#role-uid')).toBeHidden()
    }
  }
  expect(errors).toEqual([])
})

test('首次使用账号卡无虚构UID且布局稳定', async ({ page }) => {
  await page.route('**/api/bootstrap', async route => {
    const response = await route.fetch(), payload = await response.json()
    payload.state.identity = null; payload.state.cached_identity = null
    payload.overview.identity = null; payload.overview.cached_identity = null
    await route.fulfill({ response, json: payload })
  })
  await page.goto(process.env.SPRITELENS_DEMO_URL!)
  await expect(page.locator('#app')).toBeVisible()
  // 实时状态仍使用 demo 账号；首屏空账号由同一渲染入口验证。
  await page.evaluate(() => (window as unknown as { SpriteLensAccountCard: { render: (identity: null, cached: null) => void } }).SpriteLensAccountCard.render(null, null))
  await expect(page.locator('#role-name')).toHaveText('尚未识别账号')
  await expect(page.locator('#role-uid')).toHaveText('UID —')
  await expect(page.locator('#btn-uid-visibility')).toBeHidden()
})
