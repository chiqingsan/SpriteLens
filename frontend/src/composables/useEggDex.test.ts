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

const payload = { eggs: [], total: 0, shown: 0, groups: [], egg_types: [] }
const scopes: ReturnType<typeof effectScope>[] = []
afterEach(() => { scopes.splice(0).forEach(scope => scope.stop()) })
function setup(api: Parameters<typeof useEggDex>[0]) {
  const scope = effectScope(); scopes.push(scope)
  return scope.run(() => useEggDex(api))!
}
it('离页保留已加载目录，返回相同筛选不再请求', async () => {
  const api = vi.fn().mockResolvedValue(payload), model = setup(api)
  await model.resume(); const current = model.data.value
  model.pause(); await model.resume()
  expect(api).toHaveBeenCalledTimes(1); expect(model.data.value).toBe(current)
})
it('搜索 debounce 离页取消，返回按最新筛选请求，旧结果不能覆盖', async () => {
  vi.useFakeTimers()
  let resolve!: (value: unknown) => void
  const pending = new Promise<unknown>(done => { resolve = done })
  const api = vi.fn().mockResolvedValueOnce(payload).mockReturnValueOnce(pending).mockResolvedValue(payload)
  const model = setup(api); await model.load()
  model.filters.group = '旧筛选'
  model.filters.search = '新搜索'; model.pause(); vi.runAllTimers()
  expect(api).toHaveBeenCalledTimes(2)
  await model.resume(); const current = model.data.value
  expect(api).toHaveBeenCalledTimes(3); expect(api.mock.calls[2]![0]).toContain('search=')
  resolve({ ...payload, total: 99 }); await pending; await Promise.resolve()
  expect(model.data.value).toBe(current)
})
it('隐藏时筛选变化不发请求，返回加载；失败后再次返回可重试', async () => {
  const api = vi.fn().mockResolvedValueOnce(payload).mockRejectedValueOnce(new Error('读取失败')).mockResolvedValue(payload)
  const model = setup(api); await model.load(); model.pause()
  model.filters.group = '新筛选'
  expect(api).toHaveBeenCalledTimes(1)
  await model.resume(); expect(model.error.value).toBe('读取失败')
  model.pause(); await model.resume()
  expect(api).toHaveBeenCalledTimes(3); expect(model.error.value).toBe('')
})

it('清除多个筛选只请求一次完整目录，且可等待请求完成', async () => {
  const api = vi.fn().mockResolvedValue(payload), model = setup(api)
  model.pause()
  model.filters.search = '旧搜索'; model.filters.group = '动物组'; model.filters.egg_type = '普通'
  await model.resume()
  api.mockClear()
  await model.clear()
  expect(api).toHaveBeenCalledTimes(1)
  expect(api.mock.calls[0]![0]).toBe('/api/eggs?')
  expect(model.loading.value).toBe(false)
})
