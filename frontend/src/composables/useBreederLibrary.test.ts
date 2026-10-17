import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useBreederLibrary } from './useBreederLibrary'
import { parseBreederLibrary, type BreederLibrary } from '../types/breederLibrary'

const payload = (uid = 101): BreederLibrary => ({ uid, version: 1, available: true, source: 'observed', pet_count: 0,
  groups: [], natures: [], males: [], females: [], male_total: 0, female_total: 0, page_size: 24,
  male_page: 1, female_page: 1, selected_male: null, selected_female: null, anchor: 0, selection_changed: false, prediction: null })
function deferred() {
  let resolve!: (value: unknown) => void
  const promise = new Promise<unknown>(done => { resolve = done })
  return { promise, resolve }
}
function host() {
  return { load: vi.fn(async (): Promise<unknown> => payload()), cancel: vi.fn(),
    context: () => ({ uid: 101, version: 1, generation: 1 }), openPet: vi.fn() }
}
beforeEach(() => { vi.useFakeTimers() })
afterEach(() => { vi.useRealTimers() })
describe('筛选配对请求和账号隔离', () => {
  it('输入立即使旧请求失效，乱序和离页响应不覆盖结果', async () => {
    const first = deferred(), next = deferred(), leaving = deferred(), h = host()
    h.load.mockReturnValueOnce(first.promise).mockReturnValueOnce(next.promise).mockReturnValueOnce(leaving.promise)
    const model = useBreederLibrary(h), old = model.load()
    model.filters.search = '新的条件'
    first.resolve({ ...payload(), pet_count: 100 }); await old
    expect(model.data.value).toBeNull()
    await vi.advanceTimersByTimeAsync(180)
    next.resolve({ ...payload(), pet_count: 2 }); await Promise.resolve(); await Promise.resolve()
    expect(model.data.value?.pet_count).toBe(2)
    model.filters.search = '离页'; const request = model.load(); model.pause()
    leaving.resolve(payload()); await request
    expect(model.data.value?.pet_count).toBe(2)
    expect(h.cancel).toHaveBeenCalled()
  })
  it('切号清空筛选和亲本，并拒绝其他账号载荷', async () => {
    const h = host(), model = useBreederLibrary(h)
    await model.load(); model.filters.groups = ['动物']; model.male.value = '9007199254740993'
    model.resetAccount()
    h.context = () => ({ uid: 202, version: 1, generation: 2 })
    await model.load()
    expect(model.data.value).toBeNull()
    expect(model.filters.groups).toEqual([]); expect(model.male.value).toBe('')
    h.load.mockResolvedValueOnce(payload(202)); await model.load()
    expect(model.data.value?.uid).toBe(202)
    model.pause()
  })
  it('返回页面复用快照，失败保留结果并可重试，无效范围不发请求', async () => {
    const h = host(), model = useBreederLibrary(h)
    await model.load(); model.pause(); await model.load()
    expect(h.load).toHaveBeenCalledTimes(1)
    h.load.mockRejectedValueOnce(new Error('读取失败')); model.refresh(); await Promise.resolve(); await Promise.resolve()
    expect(model.data.value?.uid).toBe(101); expect(model.error.value).toBe('读取失败')
    await model.load(); expect(model.error.value).toBe('')
    model.filters.height_min = 90; model.filters.height_max = 10
    const calls = h.load.mock.calls.length
    await vi.advanceTimersByTimeAsync(200)
    expect(model.invalidRange.value).toBe(true); expect(h.load).toHaveBeenCalledTimes(calls)
    model.pause()
  })
  it('百分比转为后端区间比，同性格开关清除旧亲本', async () => {
    const h = host(), model = useBreederLibrary(h)
    await model.load(); model.filters.weight_min = 98; model.male.value = '123'; model.anchor.value = 1
    model.filters.same_nature = false
    await vi.advanceTimersByTimeAsync(200)
    expect(h.load.mock.lastCall?.[0]).toMatchObject({ weight_min: .98, same_nature: 0, male: '', anchor: 0 })
    model.pause()
  })
  it('DTO拒绝不完整预测和亲本字段，避免类型断言掩盖坏数据', () => {
    expect(() => parseBreederLibrary({ ...payload(), prediction: { groups: [] } })).toThrow()
    expect(() => parseBreederLibrary({ ...payload(), males: [{ gid: '1' }] })).toThrow()
  })
  it('双头滑条交叉时联动另一端，回到边界恢复不限并提交查询', async () => {
    const h = host(), model = useBreederLibrary(h)
    await model.load()
    model.range('weight', 'max', 90, false)
    model.range('weight', 'min', 98, true)
    await Promise.resolve(); await Promise.resolve()
    expect(model.filters.weight_min).toBe(98); expect(model.filters.weight_max).toBe(98)
    expect(h.load.mock.lastCall?.[0]).toMatchObject({ weight_min: .98, weight_max: .98 })
    model.range('weight', 'max', 100, false); model.range('weight', 'min', 0, true)
    expect(model.filters.weight_min).toBeNull(); expect(model.filters.weight_max).toBeNull()
    model.range('voice', 'min', 60, false); model.range('voice', 'max', -80, true)
    expect(model.filters.voice_min).toBe(-80); expect(model.filters.voice_max).toBe(-80)
    model.range('voice', 'min', -100, false); model.range('voice', 'max', 100, true)
    expect(model.filters.voice_min).toBeNull(); expect(model.filters.voice_max).toBeNull()
    model.pause()
  })
})
