import { test, expect } from '@playwright/test'

test('browser mode keeps the desktop controls hidden', async ({ page }) => {
  await page.goto(process.env.SPRITELENS_DEMO_URL!)
  await expect(page.locator('#app')).toBeVisible()
  await expect(page.locator('#desktop-titlebar')).toBeHidden()
  await expect(page.locator('.window-resize-right')).toBeHidden()
})

test('desktop controls follow native state and stay available during startup failure', async ({ page }) => {
  await page.addInitScript(() => {
    const calls: string[] = []
    let maximized = false
    const update = () => window.dispatchEvent(new CustomEvent('desktop-window-state', {
      detail: { maximized, minimized: false },
    }))
    Object.assign(window, {
      desktopTestCalls: calls,
      pywebview: { api: {
        get_window_state: async () => ({ maximized, minimized: false }),
        toggle_maximize: async (...args: unknown[]) => {
          if (args.length) throw new Error('unexpected window action argument')
          calls.push('maximize'); maximized = !maximized; update()
        },
        minimize: async (...args: unknown[]) => {
          if (args.length) throw new Error('unexpected window action argument')
          calls.push('minimize')
        },
        close: async () => { calls.push('close') },
        resize_window: async (edge: number) => { calls.push(`resize:${edge}`) },
      } },
    })
    window.addEventListener('DOMContentLoaded', () => window.dispatchEvent(new Event('pywebviewready')))
  })
  await page.goto(process.env.SPRITELENS_DEMO_URL!)
  await expect(page.locator('#desktop-titlebar')).toBeVisible()
  await expect(page.locator('#app')).toBeVisible()
  const bar = await page.locator('#desktop-titlebar').boundingBox()
  const app = await page.locator('#app').boundingBox()
  expect(bar!.height).toBe(40)
  expect(app!.y).toBe(40)
  await page.getByRole('button', { name: '最大化', exact: true }).click()
  await expect(page.getByRole('button', { name: '还原窗口' })).toBeVisible()
  await expect(page.locator('.window-resize-right')).toBeHidden()
  // 浏览器没有 Windows 的非客户区；原生拖动区域的双击不再派发 JS 操作。
  await page.locator('.window-drag-area').dblclick()
  await expect(page.getByRole('button', { name: '还原窗口' })).toBeVisible()
  await page.getByRole('button', { name: '还原窗口' }).click()
  await expect(page.getByRole('button', { name: '最大化', exact: true })).toBeVisible()
  await expect(page.locator('.window-resize-right')).toBeVisible()
  const grip = await page.locator('.window-resize-right').boundingBox()
  await page.mouse.move(grip!.x + 2, grip!.y + 100)
  await page.mouse.down()
  await page.mouse.move(grip!.x - 50, grip!.y + 100)
  await page.mouse.up()
  await page.getByRole('button', { name: '最小化', exact: true }).click()
  await page.evaluate(() => {
    document.getElementById('app')!.hidden = true
    document.getElementById('startup')!.hidden = false
  })
  await expect(page.locator('#desktop-titlebar')).toBeVisible()
  await page.getByRole('button', { name: '关闭', exact: true }).click()
  const calls = await page.evaluate(() => (window as unknown as { desktopTestCalls: string[] }).desktopTestCalls)
  expect(calls).toEqual(['maximize', 'maximize', 'resize:2', 'minimize', 'close'])
})
