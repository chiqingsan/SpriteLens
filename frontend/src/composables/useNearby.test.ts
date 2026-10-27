import { flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi } from 'vitest'
import { AUTO_LOAD_INTERVAL_MS, useNearby } from './useNearby'
import { parseNearby } from '../types/nearby'

const summary = { uid: '101', version: 1, observation_id: 1, phase: 'observing' }
const actor = { actor_id: '9007199254740993', position: [10, 20, null], config_id: 10011, base_id: 3004, name: '迪莫', icon_url: '', type_names: [], level: 0, height: 0, weight: null, voice: -100, updated_at: 1, marks: [{ label: '粗', name: '粗嗓门', source: 'reference' }], attention: 'marked', chain_names: [] }
const snapshot = { ...summary, player_position: [0, 0, 0], position_source: 'client_target', complete: false, source: 'observed_partial', mapping_available: true, radar_radius_raw: 10000, scene_id: 1, updated_at: 1, unresolved_updates: 0, rejected_actors: 0, actors: [actor] }
describe('附近精灵请求归属', () => {
  it('切换到版本较小的账号立即取消旧请求并读取新账号', async () => {
    const load = vi.fn().mockImplementationOnce(() => new Promise(() => {}))
      .mockResolvedValueOnce({ ...snapshot, uid: '202', version: 1 })
    const model = useNearby({ load })
    model.update({ ...summary, version: 100 })
    const previousSignal = load.mock.calls[0]![0] as AbortSignal
    model.update({ ...summary, uid: '202', version: 1 })
    expect(previousSignal.aborted).toBe(true)
    await flushPromises()
    expect(model.data.value?.uid).toBe('202')
    model.pause()
  })
  it('持续推送领先于慢请求时仍提交同周期进展，摘要不降级', async () => {
    const pending: Array<(value: unknown) => void> = []
    const load = vi.fn(() => new Promise(resolve => pending.push(resolve)))
    const model = useNearby({ load })
    model.update(summary)
    model.update({ ...summary, version: 2 })
    pending[0]!(snapshot); await flushPromises()
    expect(model.data.value?.version).toBe(1)
    expect(model.summary.value?.version).toBe(2)
    model.update({ ...summary, version: 3 })
    pending[1]!({ ...snapshot, version: 2 }); await flushPromises()
    expect(model.data.value?.version).toBe(2)
    expect(model.summary.value?.version).toBe(3)
    model.pause()
  })
  it('隐藏页面暂停请求但仍清理旧周期，回页重新获取相同摘要', async () => {
    const load = vi.fn().mockResolvedValueOnce(snapshot).mockResolvedValueOnce({ ...snapshot, version: 2, observation_id: 2 })
    const model = useNearby({ load }); model.update(summary); await flushPromises()
    model.pause()
    const next = { ...summary, version: 2, observation_id: 2 }
    model.update(next)
    expect(model.data.value).toBeNull(); expect(load).toHaveBeenCalledTimes(1)
    model.resume(); model.update(next); await flushPromises()
    expect(model.data.value?.observation_id).toBe(2)
    model.pause()
  })
  it('保留字符串实体 ID、零值和未知值，拒绝非法响应', () => {
    expect(parseNearby(snapshot).actors[0]).toEqual(actor)
    const legacy = { ...snapshot, actors: [{ ...actor, marks: undefined, attention: undefined }] }
    expect(() => parseNearby(legacy)).toThrow()
    expect(parseNearby({ ...snapshot, observation_id: undefined }).observation_id).toBe(0)
    expect(parseNearby(snapshot).radar_radius_raw).toBe(10000)
    expect(parseNearby({ ...snapshot, radar_radius_raw: 2500 }).radar_radius_raw).toBe(2500)
    expect(() => parseNearby({ ...snapshot, radar_radius_raw: 0 })).toThrow()
    expect(() => parseNearby({ ...snapshot, radar_radius_raw: 12.5 })).toThrow()
    expect(() => parseNearby({ ...snapshot, actors: [{ ...actor, actor_id: 9007199254740993 }] })).toThrow()
    expect(() => parseNearby({ ...snapshot, complete: true })).toThrow()
  })
  it('切号后立即清空，旧请求晚到不能覆盖新观察', async () => {
    let resolve: (value: unknown) => void = () => {}
    const load = vi.fn().mockResolvedValueOnce(snapshot).mockImplementationOnce(() => new Promise(r => { resolve = r })).mockResolvedValueOnce({ ...snapshot, uid: '202', version: 3, observation_id: 2, actors: [] })
    const model = useNearby({ load }); model.update(summary); await flushPromises()
    expect(model.data.value?.actors).toHaveLength(1)
    // 旧账号的手动刷新还在途：节流不会推迟它，切号必须立刻取消并清空。
    void model.load()
    const previousSignal = load.mock.calls[1]![0] as AbortSignal
    model.update({ ...summary, uid: '202', version: 3, observation_id: 2 })
    expect(previousSignal.aborted).toBe(true)
    expect(model.data.value).toBeNull(); await flushPromises()
    resolve({ ...snapshot, version: 2 }); await flushPromises()
    expect(model.data.value?.uid).toBe('202'); expect(model.data.value?.actors).toEqual([])
  })
  it('同场景传送/战斗的观察周期改变时立即清空；旧版本不接纳', async () => {
    const load = vi.fn().mockResolvedValue(snapshot)
    const model = useNearby({ load }); model.update(summary); await flushPromises()
    model.update({ ...summary, version: 2, observation_id: 2, phase: 'battle_unverified' })
    expect(model.data.value).toBeNull(); await flushPromises()
    expect(model.data.value).toBeNull()
    model.update(summary); expect(load).toHaveBeenCalledTimes(2)
  })
  it('刷新失败保留同周期数据并标记，离页后忽略成功与失败响应', async () => {
    let resolve: (value: unknown) => void = () => {}
    const load = vi.fn().mockResolvedValueOnce(snapshot).mockRejectedValueOnce(Error('读取失败')).mockImplementationOnce(() => new Promise(r => { resolve = r }))
    const model = useNearby({ load }); model.update(summary); await flushPromises()
    await model.load()
    expect(model.error.value).toBe('读取失败'); expect(model.stale.value).toBe(true)
    expect(model.data.value?.version).toBe(1); expect(model.data.value?.actors).toHaveLength(1)
    const pending = model.load(); model.pause(); resolve({ ...snapshot, version: 5 }); await pending
    expect(model.data.value?.version).toBe(1); expect(model.loading.value).toBe(false)
  })
  it('失败且无数据时维持错误空态', async () => {
    const load = vi.fn().mockRejectedValue(Error('网络不可用'))
    const model = useNearby({ load })
    await model.load()
    expect(model.data.value).toBeNull(); expect(model.stale.value).toBe(false)
    expect(model.error.value).toBe('网络不可用'); expect(model.loading.value).toBe(false)
  })
  it('观察周期变化时清除失败标记', async () => {
    const load = vi.fn().mockResolvedValueOnce(snapshot).mockRejectedValueOnce(Error('读取失败'))
      .mockResolvedValue({ ...snapshot, version: 3, observation_id: 2, actors: [] })
    const model = useNearby({ load }); model.update(summary); await flushPromises()
    await model.load(); expect(model.stale.value).toBe(true)
    model.update({ ...summary, version: 3, observation_id: 2 })
    expect(model.data.value).toBeNull(); expect(model.stale.value).toBe(false); expect(model.error.value).toBe('')
    await flushPromises()
    expect(model.data.value?.observation_id).toBe(2)
  })
  it('解包期间合并刷新，保留当前列表直到最新快照完成', async () => {
    let resolve: (value: unknown) => void = () => {}
    const load = vi.fn().mockImplementationOnce(() => new Promise(r => { resolve = r })).mockResolvedValueOnce({ ...snapshot, version: 3 })
    const model = useNearby({ load })
    model.update(summary)
    model.update({ ...summary, version: 2 })
    model.update({ ...summary, version: 3 })
    expect(load).toHaveBeenCalledOnce()
    resolve({ ...snapshot, version: 1 }); await flushPromises()
    expect(load).toHaveBeenCalledTimes(2)
    await flushPromises()
    expect(model.data.value?.version).toBe(3)
  })

  it('版本推进触发的后台同步不切换 loading，只原位更新已提交的数据', async () => {
    let resolve: (value: unknown) => void = () => {}
    const load = vi.fn().mockResolvedValueOnce(snapshot).mockImplementationOnce(() => new Promise(r => { resolve = r }))
    const model = useNearby({ load }); model.update(summary); await flushPromises()
    model.update({ ...summary, version: 2 }); await flushPromises()
    expect(model.loading.value).toBe(false)
    expect(model.data.value?.version).toBe(1)
    resolve({ ...snapshot, version: 2 }); await flushPromises()
    expect(model.data.value?.version).toBe(2)
    expect(model.loading.value).toBe(false)
    model.pause()
  })
  it('自动同步按最小间隔合并，窗口内多次推进只补发一次最新', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    try {
      const load = vi.fn().mockResolvedValueOnce(snapshot)
        .mockResolvedValueOnce({ ...snapshot, version: 2 })
        .mockResolvedValueOnce({ ...snapshot, version: 5 })
      const model = useNearby({ load })
      model.update(summary)
      expect(model.loading.value).toBe(true)
      await flushPromises()
      expect(model.data.value?.version).toBe(1)
      // 距上次自动读取足够久：领先的版本推进立即读一次。
      model.update({ ...summary, version: 2 }); await flushPromises()
      expect(load).toHaveBeenCalledTimes(2)
      expect(model.data.value?.version).toBe(2)
      model.update({ ...summary, version: 3 })
      model.update({ ...summary, version: 4 })
      model.update({ ...summary, version: 5 })
      expect(load).toHaveBeenCalledTimes(2)
      vi.advanceTimersByTime(AUTO_LOAD_INTERVAL_MS)
      await flushPromises()
      expect(load).toHaveBeenCalledTimes(3)
      expect(model.data.value?.version).toBe(5)
      expect(model.loading.value).toBe(false)
      model.pause()
    } finally { vi.useRealTimers() }
  })
  it('暂停后不再排程后台同步，恢复时立即补一次积压的读取', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    try {
      const load = vi.fn().mockResolvedValueOnce(snapshot)
        .mockResolvedValueOnce({ ...snapshot, version: 2 })
        .mockResolvedValueOnce({ ...snapshot, version: 3 })
      const model = useNearby({ load })
      model.update(summary); await flushPromises()
      model.update({ ...summary, version: 2 }); await flushPromises()
      expect(load).toHaveBeenCalledTimes(2)
      model.update({ ...summary, version: 3 })
      model.pause()
      vi.advanceTimersByTime(AUTO_LOAD_INTERVAL_MS * 2)
      await flushPromises()
      expect(load).toHaveBeenCalledTimes(2)
      model.resume(); await flushPromises()
      expect(load).toHaveBeenCalledTimes(3)
      expect(model.data.value?.version).toBe(3)
      expect(model.loading.value).toBe(false)
      model.pause()
    } finally { vi.useRealTimers() }
  })
  it('同周期失败只标记稍早结果，不会自动重试', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    try {
      const load = vi.fn().mockResolvedValueOnce(snapshot).mockRejectedValueOnce(Error('读取失败'))
      const model = useNearby({ load })
      model.update(summary); await flushPromises()
      model.update({ ...summary, version: 2 }); await flushPromises()
      expect(model.error.value).toBe('读取失败')
      expect(model.stale.value).toBe(true)
      expect(model.data.value?.version).toBe(1)
      vi.advanceTimersByTime(AUTO_LOAD_INTERVAL_MS * 4)
      await flushPromises()
      expect(load).toHaveBeenCalledTimes(2)
      model.pause()
    } finally { vi.useRealTimers() }
  })
  it('切号状态短暂缺少附近观察时清空旧账号数据', async () => {
    const load = vi.fn().mockResolvedValue(snapshot)
    const model = useNearby({ load }); model.update(summary); await flushPromises()
    model.update(null)
    expect(model.data.value).toBeNull(); expect(model.summary.value).toBeNull(); expect(model.loading.value).toBe(false)
  })
})
