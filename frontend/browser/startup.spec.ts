import { test, expect } from '@playwright/test'
import { resolve } from 'node:path'

test('desktop hint keeps web logo hidden before a delayed bridge', async ({ page }) => {
  let release!: () => void
  const gate = new Promise<void>(done => { release = done })
  await page.route('**/api/bootstrap', async route => { await gate; await route.continue() })
  const url = process.env.SPRITELENS_DEMO_URL!.replace('/#', '/?desktop=1#')
  await page.goto(url, { waitUntil: 'domcontentloaded' })
  await expect(page.locator('#startup img')).toBeHidden()
  await expect(page.locator('#app')).toBeHidden()
  release()
})

for (const bridgeTiming of ['early', 'late']) {
  test(`desktop startup reports readiness after the first screen with a ${bridgeTiming} bridge`, async ({ page }) => {
    await page.addInitScript(() => {
      const calls: string[] = []
      Object.assign(window, {
        startupTestCalls: calls,
        connectStartupBridge: () => {
          Object.assign(window, { pywebview: { api: {
            startup_ready: async () => { calls.push('ready') },
            startup_failed: async (reason: string) => { calls.push(reason) },
            get_window_state: async () => ({ maximized: false, minimized: false }),
          } } })
          window.dispatchEvent(new Event('pywebviewready'))
        },
      })
    })
    let release!: () => void
    const gate = new Promise<void>(done => { release = done })
    await page.route('**/api/bootstrap', async route => { await gate; await route.continue() })
    await page.goto(process.env.SPRITELENS_DEMO_URL!, { waitUntil: 'domcontentloaded' })
    const connect = () => page.evaluate(() => (window as unknown as { connectStartupBridge: () => void }).connectStartupBridge())
    const calls = () => page.evaluate(() => (window as unknown as { startupTestCalls: string[] }).startupTestCalls)
    if (bridgeTiming === 'early') {
      await connect()
      await expect(page.locator('#startup')).toBeHidden()
      expect(await calls()).toEqual([])
    }
    release()
    await expect(page.getByText('宠物总数', { exact: true })).toBeVisible()
    await expect(page.locator('#startup')).toBeHidden()
    if (bridgeTiming === 'late') await connect()
    await expect.poll(calls).toEqual(['ready'])
  })
}

test('desktop resource failure reaches a bridge that becomes available after the failure', async ({ page }) => {
  await page.route('**/static/app.css', route => route.abort())
  await page.goto(process.env.SPRITELENS_DEMO_URL!, { waitUntil: 'domcontentloaded' })
  await expect(page.locator('[data-startup-message]')).toContainText('样式')
  await page.evaluate(() => {
    const calls: string[] = []
    Object.assign(window, { startupTestCalls: calls, pywebview: { api: {
      startup_ready: async () => { calls.push('ready') },
      startup_failed: async (reason: string) => { calls.push(reason) },
      get_window_state: async () => ({ maximized: false, minimized: false }),
    } } })
    window.dispatchEvent(new Event('pywebviewready'))
  })
  await expect(page.locator('#startup')).toBeHidden()
  await expect(page.locator('#app')).toBeHidden()
  const calls = await page.evaluate(() => (window as unknown as { startupTestCalls: string[] }).startupTestCalls)
  expect(calls).toHaveLength(1)
  expect(calls[0]).toContain('样式')
})

test('startup cover waits for initial data and Vue entry before revealing the first screen', async ({ page }) => {
  let releaseBootstrap!: () => void
  let releaseVue!: () => void
  const bootstrapGate = new Promise<void>(done => { releaseBootstrap = done })
  const vueGate = new Promise<void>(done => { releaseVue = done })
  await page.route('**/api/bootstrap', async route => { await bootstrapGate; await route.continue() })
  await page.route('**/static/vue/entry.js', async route => { await vueGate; await route.continue() })
  await page.goto(process.env.SPRITELENS_DEMO_URL!, { waitUntil: 'domcontentloaded' })
  await expect(page.locator('#startup')).toBeVisible()
  await expect(page.locator('#startup img')).toBeVisible()
  await expect(page.locator('[data-startup-message]')).toHaveText('正在启动…')
  await expect(page.locator('#app')).toBeHidden()
  await page.screenshot({ path: resolve('..', '.guishot/startup-overlay.png') })
  const vueRequested = page.waitForRequest('**/static/vue/entry.js')
  releaseBootstrap()
  await vueRequested
  await expect(page.locator('#startup')).toBeVisible()
  await expect(page.locator('#app')).toBeHidden()
  releaseVue()
  await expect(page.locator('#app')).toBeVisible()
  await expect(page.getByText('宠物总数', { exact: true })).toBeVisible()
  await expect(page.locator('#startup')).toBeHidden()
})

test('stylesheet failure retains the inline cover and retry recovers with reduced motion', async ({ page }) => {
  await page.route('**/static/app.css', route => route.abort())
  await page.goto(process.env.SPRITELENS_DEMO_URL!, { waitUntil: 'domcontentloaded' })
  await expect(page.locator('#startup')).toBeVisible()
  await expect(page.locator('[data-startup-message]')).toContainText('样式')
  await expect(page.getByRole('button', { name: '重新加载' })).toBeVisible()
  await expect(page.locator('#app')).toBeHidden()
  await page.unroute('**/static/app.css')
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.getByRole('button', { name: '重新加载' }).click()
  await expect(page.locator('#app')).toBeVisible()
  await expect(page.locator('#startup')).toBeHidden()
})
