import { effectScope, nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useEggDex } from './useEggDex'
import { dex } from '../testData'

afterEach(() => vi.useRealTimers())
describe('蛋图鉴请求生命周期', () => {
  it('取消晚到仍只提交最新请求；离页后不提交', async () => {
    const pending: Array<{ resolve: (data: unknown) => void; signal?: AbortSignal }> = []
    const api = vi.fn((_path: string, signal?: AbortSignal) => new Promise<unknown>(resolve => pending.push({ resolve, signal })))
    const scope = effectScope()
    const page = scope.run(() => useEggDex(api))!
    const first = page.load()
    page.filters.group = '动物组'
    expect(pending[0].signal?.aborted).toBe(true)
    pending[1].resolve(dex)
    await nextTick(); await Promise.resolve()
    pending[0].resolve({ ...dex, shown: 0, eggs: [] })
    await first
    expect(page.data.value?.shown).toBe(1)
    const last = page.load()
    scope.stop()
    pending[2].resolve({ ...dex, shown: 0, eggs: [] })
    await last
    expect(pending[2].signal?.aborted).toBe(true)
    expect(page.data.value?.shown).toBe(1)
  })
  it('搜索 debounce 期间立即丢弃旧响应', async () => {
    vi.useFakeTimers()
    let resolve!: (value: unknown) => void
    const api = vi.fn(() => new Promise<unknown>(done => { resolve = done }))
    const scope = effectScope()
    const page = scope.run(() => useEggDex(api))!
    const first = page.load()
    page.filters.search = '喵'
    resolve(dex)
    await first
    expect(page.data.value).toBeNull()
    scope.stop()
    await vi.runAllTimersAsync()
    expect(api).toHaveBeenCalledTimes(1)
  })
  it('坏载荷和服务失败可见，支持重试', async () => {
    const api = vi.fn().mockResolvedValueOnce({ eggs: [{ egg_conf_id: '3001001' }] }).mockRejectedValueOnce(new Error('读取失败')).mockResolvedValue(dex)
    const scope = effectScope()
    const page = scope.run(() => useEggDex(api))!
    await page.load()
    expect(page.error.value).toContain('格式不正确')
    await page.load()
    expect(page.error.value).toBe('读取失败')
    await page.load()
    expect(page.error.value).toBe('')
    expect(page.data.value?.shown).toBe(1)
    scope.stop()
  })
})
