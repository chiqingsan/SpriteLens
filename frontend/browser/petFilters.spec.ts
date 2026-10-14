import { test, expect, type Page } from '@playwright/test'

async function apply(page: Page, action: () => Promise<unknown>) {
  const response = page.waitForResponse(result => new URL(result.url()).pathname === '/api/pets')
  await action()
  const data = await (await response).json()
  await expect(page.locator('#pet-grid')).toHaveAttribute('aria-busy', 'false')
  return data
}

test('基础筛选、空态与排序控件', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto(process.env.SPRITELENS_DEMO_URL!)
  await expect(page.locator('#app')).toBeVisible()
  await apply(page, () => page.locator('[data-page="pets"]').click())
  await page.locator('#pet-view [data-view="point"]').click()
  await expect(page.locator('#f-sort')).toBeHidden()
  await page.locator('#pet-view [data-view="card"]').click()
  await expect(page.locator('#f-sort')).toBeVisible()
  if (await page.locator('#btn-pet-filters').isVisible()) await page.locator('#btn-pet-filters').click()
  const empty = await apply(page, () => page.locator('#f-search').fill('不存在的合成精灵'))
  expect(empty.shown).toBe(0)
  await expect(page.locator('#pet-empty-copy')).toContainText('没有符合筛选条件')
  await apply(page, () => page.locator('#btn-empty-reset').click())
  await expect(page.locator('#f-search')).toHaveValue('')
  const sorted = await apply(page, () => page.locator('#f-sort').selectOption('level'))
  const levels = sorted.pets.map((pet: { level: number }) => pet.level)
  expect(levels).toEqual([...levels].sort((a: number, b: number) => a - b))
  const male = await apply(page, () => page.locator('#f-gender button').first().click())
  expect(male.pets.length).toBeGreaterThan(0)
  expect(male.pets.every((pet: { gender: number }) => pet.gender === 1)).toBe(true)
  await apply(page, () => page.locator('#f-gender button').first().click())
  await expect(page.locator('#f-gender button').first()).toHaveAttribute('aria-pressed', 'false')
  await page.locator('details').filter({ has: page.locator('#f-level-label') }).locator('summary').click()
  const low = page.locator('#f-level-min'), high = page.locator('#f-level-max')
  const bounds = (await low.boundingBox())!
  await apply(page, async () => {
    await page.mouse.move(bounds.x + 9, bounds.y + bounds.height / 2); await page.mouse.down()
    await page.mouse.move(bounds.x + 9 + (bounds.width - 18) * .2, bounds.y + bounds.height / 2, { steps: 5 }); await page.mouse.up()
  })
  expect(Number(await low.inputValue())).toBeGreaterThan(1)
  const interval = await apply(page, async () => {
    await page.mouse.move(bounds.x + bounds.width - 9, bounds.y + bounds.height / 2); await page.mouse.down()
    await page.mouse.move(bounds.x + 9 + (bounds.width - 18) * .7, bounds.y + bounds.height / 2, { steps: 5 }); await page.mouse.up()
  })
  expect(Number(await high.inputValue())).toBeLessThan(60)
  expect(interval.pets.every((pet: { level: number }) => pet.level >= interval.filters.level_min && pet.level <= interval.filters.level_max)).toBe(true)
  await page.locator('#pet-filters').screenshot({ path: 'test-results/pet-level-range.png' })
  await apply(page, () => low.press('Home'))
  await apply(page, () => high.press('End'))
  const maxed = await apply(page, () => low.press('End'))
  expect(maxed.pets.every((pet: { level: number }) => pet.level >= 60)).toBe(true)
  await expect(page.locator('#f-level-label')).toHaveText('60 – 60')
  await apply(page, async () => {
    await page.mouse.move(bounds.x + bounds.width - 13, bounds.y + bounds.height / 2); await page.mouse.down()
    await page.mouse.move(bounds.x + 9 + (bounds.width - 18) * .4, bounds.y + bounds.height / 2, { steps: 5 }); await page.mouse.up()
  })
  expect(Number(await low.inputValue())).toBeLessThan(60)
  await expect(high).toHaveValue('60')
  await apply(page, () => page.locator('#btn-reset-filters').click())
  await page.locator('details').filter({ has: page.locator('#f-natures') }).locator('summary').click()
  const nature = page.locator('#f-natures .chip').first()
  await nature.focus()
  await apply(page, () => nature.press('Enter'))
  await expect(nature).toHaveAttribute('aria-pressed', 'true')
  await expect(nature).toBeFocused()
  await apply(page, () => page.locator('#btn-reset-filters').click())
  await page.locator('#pet-view [data-view="card"]').click()
  await expect(page.locator('#f-sort')).toBeVisible()
  await page.locator('#pet-view [data-view="point"]').click()
  await expect(page.locator('#f-sort')).toBeHidden()
  expect(errors).toEqual([])
})

test('离页取消延迟搜索，返回无重复控件，错误选项可见且能重试', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto(process.env.SPRITELENS_DEMO_URL!)
  await expect(page.locator('#app')).toBeVisible()
  await apply(page, () => page.locator('[data-page="pets"]').click())
  const searches: string[] = []
  page.on('request', request => {
    const url = new URL(request.url())
    if (url.pathname === '/api/pets') searches.push(url.searchParams.get('search') || '')
  })
  await page.clock.install()
  await page.locator('#f-search').fill('迪莫')
  await page.locator('[data-page="egg-dex"]').click()
  await page.clock.fastForward(500)
  expect(searches).not.toContain('迪莫')
  await apply(page, () => page.locator('[data-page="pets"]').click())
  await expect(page.locator('#f-search')).toHaveValue('迪莫')
  expect(await page.locator('#f-search').count()).toBe(1)
  await page.route('**/api/pets?*', async route => {
    const data = await (await route.fetch()).json()
    data.options.talent_max = '错误类型'
    await route.fulfill({ json: data })
  })
  await apply(page, () => page.locator('#f-search').fill('火神').then(() => page.clock.fastForward(300)))
  await expect(page.locator('#toast-layer')).toContainText('筛选选项格式不正确')
  await page.unroute('**/api/pets?*')
  await apply(page, () => page.locator('[data-page="pets"]').click())
  await expect(page.locator('#pet-count')).not.toHaveText('加载失败')
  expect(errors).toEqual([])
})

test('防抖等待期间立即失效旧响应，取消无效也不提交', async ({ page }) => {
  await page.addInitScript(() => {
    const original = window.fetch
    window.fetch = (input, options) => original(input,
      String(input).startsWith('/api/pets') ? { ...options, signal: undefined } : options)
  })
  await page.goto(process.env.SPRITELENS_DEMO_URL!)
  await expect(page.locator('#app')).toBeVisible()
  await apply(page, () => page.locator('[data-page="pets"]').click())
  await page.locator('#pet-view [data-view="card"]').click()
  await page.clock.install()
  let releaseOld!: () => void
  await page.route('**/api/pets?*', async route => {
    const data = await (await route.fetch()).json()
    if (new URL(route.request().url()).searchParams.get('search') === '迪莫') {
      for (const pet of data.pets) pet.name = '被拒绝的旧精灵'
      await new Promise<void>(done => { releaseOld = done })
    }
    await route.fulfill({ json: data })
  })
  await page.locator('#f-search').fill('迪莫')
  await page.clock.fastForward(300)
  await expect.poll(() => Boolean(releaseOld)).toBe(true)
  await page.locator('#f-search').fill('火神')
  const oldArrived = page.waitForResponse(response => new URL(response.url()).searchParams.get('search') === '迪莫')
  releaseOld()
  await (await oldArrived).finished()
  await page.evaluate(() => new Promise<void>(done => queueMicrotask(done)))
  await expect(page.locator('#pet-count')).toHaveText(/^命中 \d+ \/ 40 只$/)
  await expect(page.locator('#pet-grid')).not.toContainText('被拒绝的旧精灵')
  const result = await apply(page, () => page.clock.fastForward(300))
  expect(result.filters.search).toBe('火神')
  await expect(page.locator('#pet-grid')).toContainText('火神')
})

test('启动选项错误保持启动提示，重试成功后只挂载一套控件', async ({ page }) => {
  let attempts = 0
  await page.route('**/api/bootstrap', async route => {
    const data = await (await route.fetch()).json()
    if (++attempts < 3) data.pets.options.talent_max = '错误类型'
    await route.fulfill({ json: data })
  })
  await page.clock.install()
  await page.goto(process.env.SPRITELENS_DEMO_URL!)
  await expect.poll(() => attempts).toBe(1)
  await expect(page.locator('#startup')).toContainText('正在重试')
  await expect(page.locator('#app')).toBeHidden()
  await page.clock.fastForward(2100)
  await expect.poll(() => attempts).toBe(2)
  await expect(page.locator('#app')).toBeHidden()
  await page.clock.fastForward(2100)
  await expect(page.locator('#app')).toBeVisible()
  expect(await page.locator('#f-search').count()).toBe(1)
})
