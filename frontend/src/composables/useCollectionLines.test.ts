import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useCollectionLines } from './useCollectionLines'
import type { CollectionLines } from '../types/collectionLines'

const payload = (uid = 101): CollectionLines => ({ uid, version: 1, rule_version: 'test', available: true,
  source: 'observed', goal: 'big-soft', natures: [], pet_count: 0,
  totals: { eligible: 0, complete: 0, collected: 0, missingMale: 0, missing: 0, unknown: 0 }, lines: [], fathers: [] })
function deferred() {
  let resolve!: (value: unknown) => void
  const promise = new Promise<unknown>(done => { resolve = done })
  return { promise, resolve }
}
beforeEach(() => { localStorage.clear(); vi.restoreAllMocks() })
describe('双牌产线请求和账号偏好', () => {
  it('新目标请求返回后不被旧目标响应覆盖，离页丢弃未完成响应', async () => {
    const first = deferred(), second = deferred(), third = deferred()
    const host = { load: vi.fn().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise).mockReturnValueOnce(third.promise),
      cancel: vi.fn(), uid: () => 101, openPet: vi.fn() }
    const model = useCollectionLines(host)
    const old = model.load(); model.settings.value.goal = 'small-soft'; const current = model.apply()
    second.resolve({ ...payload(), goal: 'small-soft' }); await current
    first.resolve(payload()); await old
    expect(model.data.value?.goal).toBe('small-soft')
    const leaving = model.load(); model.pause(); third.resolve(payload()); await leaving
    expect(model.data.value?.goal).toBe('small-soft')
  })
  it('切号隔离数据和偏好，回到原账号恢复已保存目标', async () => {
    let uid = 101
    const host = { load: vi.fn(async () => payload(uid)), cancel: vi.fn(), uid: () => uid, openPet: vi.fn() }
    const model = useCollectionLines(host); await model.load()
    model.settings.value.goal = 'small-loud'; await model.apply()
    model.resetAccount(); uid = 202; await model.load()
    expect(model.settings.value.goal).toBe('big-soft'); expect(model.data.value?.uid).toBe(202)
    model.resetAccount(); uid = 101; await model.load()
    expect(model.settings.value.goal).toBe('small-loud')
  })
  it('加载失败保留旧结果，保存失败保留当前编辑并允许重试', async () => {
    const host = { load: vi.fn(async (): Promise<unknown> => payload()), cancel: vi.fn(), uid: () => 101, openPet: vi.fn() }
    const model = useCollectionLines(host); await model.load()
    host.load.mockRejectedValueOnce(new Error('读取失败')); await model.load()
    expect(model.data.value?.uid).toBe(101); expect(model.error.value).toBe('读取失败')
    vi.spyOn(Storage.prototype, 'setItem').mockImplementationOnce(() => { throw new Error('空间已满') })
    model.settings.value.full_weight = true; await model.apply()
    expect(model.settings.value.full_weight).toBe(true); expect(model.saveError.value).toContain('空间已满')
    await model.apply(); expect(model.saveError.value).toBe('')
    expect(JSON.parse(localStorage.getItem('spritelens.collection.101') || '{}').full_weight).toBe(true)
  })
})
