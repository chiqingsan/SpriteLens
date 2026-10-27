import { describe, expect, it, vi, afterEach } from 'vitest'
import { useWorldMaps } from './useWorldMaps'

const CATALOG = {
  schema_version: 1,
  coordinate_version: 1,
  maps: {
    '10003': {
      name: '卡洛西亚大陆', availability: 'supported',
      image: { url: '/static/maps/10003.webp', width: 4096, height: 4096 },
      projection: { origin_x: 306000, origin_y: 408000, side: 408000 },
      calibration: { level: 'verified' },
    },
  },
}

afterEach(() => vi.useRealTimers())

describe('世界地图清单读取', () => {
  it('8 秒内正常返回时写入清单', async () => {
    const state = useWorldMaps(vi.fn().mockResolvedValue(CATALOG))
    await state.refresh()
    expect(state.catalog.value?.maps['10003']?.name).toBe('卡洛西亚大陆')
    expect(state.error.value).toBe('')
    expect(state.loading.value).toBe(false)
  })

  it('接口不返回时 8 秒后报超时并保留重试入口，不留下加载态', async () => {
    vi.useFakeTimers()
    const state = useWorldMaps(vi.fn().mockImplementation(() => new Promise(() => {})))
    const pending = state.refresh()
    await vi.advanceTimersByTimeAsync(8000)
    await pending
    expect(state.error.value).toBe('地图清单请求超时，请重试')
    expect(state.catalog.value).toBeNull()
    expect(state.loading.value).toBe(false)
  })

  it('超时后重试成功时清掉错误', async () => {
    vi.useFakeTimers()
    let resolve: (value: unknown) => void = () => {}
    const load = vi.fn().mockImplementationOnce(() => new Promise(() => {}))
      .mockImplementationOnce(() => new Promise(r => { resolve = r }))
    const state = useWorldMaps(load)
    const first = state.refresh()
    await vi.advanceTimersByTimeAsync(8000)
    await first
    const retry = state.refresh()
    await vi.advanceTimersByTimeAsync(0)
    resolve(CATALOG)
    await retry
    expect(state.error.value).toBe('')
    expect(state.catalog.value?.maps['10003']?.name).toBe('卡洛西亚大陆')
  })
})
