import { effectScope, nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useHandbook } from './useHandbook'

const species = {
  key: '100', name: '火兽', display_name: '', dex_no: 1, handbook_no: '002', icon_url: '',
  egg_groups: ['动物组'], gender_ratio: [50, 50], height_range: [0, 0], weight_range: [0, 0],
  reference_ranges: { height: '0.4~0.8m', weight: '5~9kg' }, has_shiny: true,
  type_names: ['火'], type_colors: ['#e2764b'], stats: { hp: 60, atk: 60, spa: 60, def: 60, spd: 60, spe: 60, sum: 360 },
  stat_sum: 360, quality: 3, stage: 1, max_energy: 10, evolutions: [{ key: '200', name: '烈焰兽' }],
  chain_members: [{ key: '100', name: '火兽' }], collected: true, owned_count: 2, best_level: 31, description: '',
}
const payload = { species: [species], total: 1, collected: 1, shown: 1, type_options: ['火'] }
const scopes: ReturnType<typeof effectScope>[] = []
afterEach(() => { scopes.splice(0).forEach(scope => scope.stop()); vi.useRealTimers() })
function setup(api: Parameters<typeof useHandbook>[0]) {
  const scope = effectScope(); scopes.push(scope)
  return scope.run(() => useHandbook(api))!
}

describe('图鉴请求生命周期', () => {
  it('取消晚到仍只提交最新请求；离页后不提交', async () => {
    const pending: Array<{ resolve: (data: unknown) => void; signal?: AbortSignal }> = []
    const api = vi.fn((_path: string, signal?: AbortSignal) => new Promise<unknown>(resolve => pending.push({ resolve, signal })))
    const page = setup(api)
    const first = page.load()
    page.filters.type = '火'
    expect(pending[0]!.signal?.aborted).toBe(true)
    pending[1]!.resolve(payload)
    await nextTick(); await Promise.resolve()
    pending[0]!.resolve({ ...payload, shown: 0, species: [] })
    await first
    expect(page.data.value?.shown).toBe(1)
    const last = page.load()
    page.pause()
    pending[2]!.resolve({ ...payload, shown: 0, species: [] })
    await last
    expect(pending[2]!.signal?.aborted).toBe(true)
    expect(page.data.value?.shown).toBe(1)
  })
  it('搜索 debounce 期间立即丢弃旧响应', async () => {
    vi.useFakeTimers()
    let resolve!: (value: unknown) => void
    const api = vi.fn(() => new Promise<unknown>(done => { resolve = done }))
    const page = setup(api)
    const first = page.load()
    page.filters.search = '002'
    resolve(payload)
    await first
    expect(page.data.value).toBeNull()
    await vi.runAllTimersAsync()
    expect(api).toHaveBeenCalledTimes(2)
    expect(api.mock.calls[1]![0]).toContain('search=002')
  })
  it('坏载荷和服务失败可见，支持重试', async () => {
    const api = vi.fn().mockResolvedValueOnce({ species: [{ key: '100' }] })
      .mockRejectedValueOnce(new Error('读取失败')).mockResolvedValue(payload)
    const page = setup(api)
    await page.load()
    expect(page.error.value).toContain('格式不正确')
    await page.load()
    expect(page.error.value).toBe('读取失败')
    await page.load()
    expect(page.error.value).toBe('')
    expect(page.data.value?.total).toBe(1)
  })
  it('筛选映射到收集状态参数，清除筛选回到全部', async () => {
    const api = vi.fn().mockResolvedValue(payload), page = setup(api)
    await page.load()
    expect(api.mock.calls[0]![0]).toBe('/api/handbook?')
    page.filters.mode = 'uncollected'
    await nextTick()
    expect(api.mock.calls[1]![0]).toContain('uncollected=1')
    // 不能用 toContain('collected=1')：它是 uncollected=1 的子串。
    expect(api.mock.calls[1]![0]).not.toMatch(/[?&]collected=1/)
    page.filters.mode = 'collected'
    await nextTick()
    expect(api.mock.calls[2]![0]).toContain('collected=1')
    page.clear()
    await nextTick()
    expect(page.filters.mode).toBe('all')
    expect(api.mock.calls[3]![0]).toBe('/api/handbook?')
  })
})

it('离页保留已加载目录，返回相同筛选不再请求', async () => {
  const api = vi.fn().mockResolvedValue(payload), model = setup(api)
  await model.resume(); const current = model.data.value
  model.pause(); await model.resume()
  expect(api).toHaveBeenCalledTimes(1); expect(model.data.value).toBe(current)
})
it('切号清空旧账号收集状态，返回后按最新筛选重新请求', async () => {
  const api = vi.fn().mockResolvedValue(payload), model = setup(api)
  await model.load()
  model.resetAccount()
  expect(model.data.value).toBeNull()
  expect(model.error.value).toBe('')
  await model.resume()
  expect(api).toHaveBeenCalledTimes(2)
  expect(model.data.value?.total).toBe(1)
})
