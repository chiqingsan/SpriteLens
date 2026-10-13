import { test, expect } from '@playwright/test'

test('历史蛋仓不显示为当前在孵', async ({ page }) => {
  await page.route('**/api/egg-box', async route => {
    const data = await (await route.fetch()).json()
    data.source = 'historical'; data.slots_source = 'historical'
    data.hatching = null; data.historical_hatching = 1
    for (const egg of data.eggs) {
      egg.historical = true; egg.hatching = false; egg.hatch_known = false
      egg.historical_hatching = egg.instance_id === data.eggs[0].instance_id
    }
    await route.fulfill({ json: data })
  })
  await page.goto(process.env.SPRITELENS_DEMO_URL!)
  await expect(page.locator('#app')).toBeVisible()
  await page.locator('[data-page="egg-box"]').click()
  await expect(page.locator('#eb-count')).toContainText('历史缓存')
  await expect(page.locator('#eb-hatching')).toContainText('当前孵化状态未知')
  await expect(page.locator('#eb-grid .hb-card').first()).toContainText('历史在孵 · 当前未知')
})

test('切号清理账号视图，不能取消的旧响应也不能覆盖', async ({ page }) => {
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
    // 模拟传输层取消无效，强制验证晚到响应的提交校验。
    const originalFetch = window.fetch
    window.fetch = (input, options) => originalFetch(input,
      String(input).startsWith('/api/home') ? { ...options, signal: undefined } : options)
  })
  await page.goto(process.env.SPRITELENS_DEMO_URL!)
  await expect(page.locator('#app')).toBeVisible()
  await page.locator('[data-page="home"]').click()
  await expect(page.locator('#home-residents')).toContainText('护主犬')
  let requests = 0
  let releaseOld!: () => void
  await page.route('**/api/home', async route => {
    const data = await (await route.fetch()).json()
    requests++
    if (requests === 1) {
      await new Promise<void>(done => { releaseOld = done })
    } else {
      data.uid = 202; data.version += 20
      data.residents[0].name = '账号 B 居民'
    }
    await route.fulfill({ json: data })
  })
  await page.locator('[data-page="home"]').click()
  await expect.poll(() => Boolean(releaseOld)).toBe(true)
  await page.evaluate(async () => {
    const token = sessionStorage.getItem('spritelens.localToken') || ''
    const data = await (await fetch('/api/state', { headers: { 'X-Local-Token': token } })).json()
    data.uid = 202; data.identity = { uid: 202, name: '账号 B', level: 1 }
    for (const key of ['pets_version', 'egg_box_version', 'home_version', 'flower_version']) data[key] += 20
    ;(window as unknown as { accountSocket: WebSocket }).accountSocket.dispatchEvent(
      new MessageEvent('message', { data: JSON.stringify(data) }))
  })
  await expect(page.locator('#home-residents')).toContainText('账号 B 居民')
  await expect(page.locator('#pet-grid [data-gid]')).toHaveCount(0)
  await expect(page.locator('#f-natures .chip')).toHaveCount(0)
  const oldArrived = page.waitForResponse(response => response.url().endsWith('/api/home'))
  releaseOld()
  await oldArrived
  await expect(page.locator('#home-residents')).toContainText('账号 B 居民')
  await expect(page.locator('#home-residents')).not.toContainText('护主犬')
  expect(errors).toEqual([])
})
