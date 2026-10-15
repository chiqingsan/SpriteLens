import { expect, it, vi } from 'vitest'
import { usePets } from './usePets'
import { testPets } from '../petTestData'
import { parsePets } from '../types/pets'

function deferred() {
  let resolve!: (data: unknown) => void, reject!: (error: Error) => void
  const promise = new Promise<unknown>((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}
it('主动筛选转到命中箱，实时刷新保留阅读箱', async () => {
  const initial = testPets(2)
  const second = structuredClone(initial.backpack.boxes[0]!)
  second.box_id = 2; second.slots[0] = { gid: 2, state: 'matched' }
  initial.backpack.boxes.push(second)
  const filtered = structuredClone(initial)
  filtered.pets = [filtered.pets[1]!]; filtered.shown = 1; filtered.backpack.filtering = true
  filtered.backpack.boxes[0]!.matched = 0; filtered.backpack.boxes[0]!.slots[0] = { gid: 1, state: 'filtered' }
  const model = usePets(vi.fn().mockResolvedValue(filtered), () => ({ uid: 101, version: 10, generation: 1 }), () => ({}), vi.fn(), vi.fn())
  model.activate(); model.accept(initial)
  await model.load(false); expect(model.boxId.value).toBe(1)
  await model.load(); expect(model.boxId.value).toBe(2)
})
it('同页乱序、输入失效与离页即使取消无效也不能提交', async () => {
  const first = deferred(), second = deferred(), input = deferred(), leave = deferred()
  const api = vi.fn().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    .mockReturnValueOnce(input.promise).mockReturnValueOnce(leave.promise)
  const commit = vi.fn(), failed = vi.fn()
  const model = usePets(api, () => ({ uid: 101, version: 10, generation: 1 }), () => ({ search: '合成' }), commit, failed)
  model.activate()
  const a = model.load(), b = model.load()
  second.resolve(testPets(2)); await b
  first.resolve(testPets(1)); await a
  expect(model.data.value?.total).toBe(2)
  const c = model.load(); model.invalidate(); input.resolve(testPets(3)); await c
  expect(model.data.value?.total).toBe(2)
  const d = model.load(); model.pause(); leave.reject(new Error('离页网络错误')); await d
  expect(commit).toHaveBeenCalledTimes(1)
  expect(failed).not.toHaveBeenCalled()
})

it('A→B→A、错 uid 和过期版本拒绝，当前错误保留可重试状态', async () => {
  let owner = { uid: 101, version: 10, generation: 1 }
  const pending = deferred(), api = vi.fn().mockReturnValueOnce(pending.promise)
  const failed = vi.fn()
  const model = usePets(api, () => owner, () => ({}), vi.fn(), failed)
  expect(() => model.accept({ ...testPets(), uid: 202 })).toThrow('不一致')
  model.activate(); model.accept(testPets())
  const first = model.load()
  owner = { uid: 202, version: 11, generation: 2 }; model.resetAccount()
  owner = { uid: 101, version: 12, generation: 3 }; pending.resolve({ ...testPets(), version: 99 }); await first
  expect(model.data.value).toBeNull()
  api.mockResolvedValueOnce({ ...testPets(), uid: 202, version: 20 })
  await model.load(); expect(model.data.value).toBeNull()
  api.mockResolvedValueOnce({ ...testPets(), version: 11 })
  await model.load(); expect(model.data.value).toBeNull()
  api.mockRejectedValueOnce(new Error('合成失败'))
  await model.load(); expect(model.error.value).toBe('合成失败')
  api.mockResolvedValueOnce({ ...testPets(), version: 12 })
  await model.load(); expect(model.error.value).toBe(''); expect(model.data.value?.total).toBe(1)
  expect(failed).toHaveBeenCalledTimes(1)
})

it('选中箱与分页更新保持或收敛；切号清除缓存、箱号、队伍与选择', () => {
  const model = usePets(vi.fn(), () => ({ uid: 101, version: 10, generation: 1 }), () => ({}), vi.fn(), vi.fn())
  model.accept(testPets(130)); model.page.value = 5; model.selected.value = 100
  expect(model.cards.value).toHaveLength(10)
  expect(model.cardSlots.value).toHaveLength(10)
  expect(model.cardSlots.value.every(slot => slot.state === 'matched')).toBe(true)
  model.accept(testPets(2))
  expect(model.page.value).toBe(1); expect(model.selected.value).toBeNull()
  expect(model.box.value?.box_id).toBe(1)
  expect(model.slots.value.map(slot => slot.state).slice(0, 4)).toEqual(['matched', 'missing', 'unknown', 'empty'])
  model.setBox(0); expect(model.teams.value).toBe(true)
  model.resetAccount(); expect(model.data.value).toBeNull(); expect(model.box.value).toBeUndefined(); expect(model.teams.value).toBe(false)
})

it('边界契约拒绝坏槽、缺匹配个体与 unsafe ID；未知不变成空位', () => {
  const value = testPets()
  expect(parsePets(value).backpack.boxes[0]!.slots[2]!.gid).toBeNull()
  value.backpack.boxes[0]!.slots[0] = { gid: 88, state: 'matched' }
  expect(() => parsePets(value)).toThrow('不一致')
  value.backpack.boxes[0]!.slots[0] = { gid: 1, state: 'matched' }
  value.pets[0]!.gid = 9007199254740992
  expect(() => parsePets(value)).toThrow('格式不正确')
  value.pets[0]!.gid = 1; value.backpack.boxes[0]!.slots[2] = { gid: 0, state: 'unknown' }
  expect(() => parsePets(value)).toThrow('格式不正确')
})

it('当前队伍未知时保留 null，不拒绝合法宠物摘要', () => {
  const value = testPets()
  value.backpack.active_team = null
  expect(parsePets(value).backpack.active_team).toBeNull()
})

it('返回同账号同版本同筛选复用快照，版本或筛选变化才加载', async () => {
  let version = 10, search = ''
  const api = vi.fn(async () => ({ ...testPets(), version }))
  const model = usePets(api, () => ({ uid: 101, version, generation: 1 }), () => ({ search }), vi.fn(), vi.fn())
  model.accept(testPets()); model.page.value = 1; model.selected.value = 1
  model.pause(); await model.resume()
  expect(api).not.toHaveBeenCalled()
  expect(model.visible.value).toBe(true); expect(model.selected.value).toBe(1)
  model.pause(); version = 11; await model.resume()
  expect(api).toHaveBeenCalledTimes(1)
  model.pause(); search = '新筛选'; await model.resume()
  expect(api).toHaveBeenCalledTimes(2)
  expect(api.mock.calls[1]?.[0]).toContain('search=')
})

it('返回时重试失败请求，切号不复用前账号快照', async () => {
  let owner = { uid: 101, version: 10, generation: 1 }
  const api = vi.fn().mockRejectedValueOnce(new Error('失败'))
  const model = usePets(api, () => owner, () => ({}), vi.fn(), vi.fn())
  model.activate(); model.accept(testPets()); await model.load()
  model.pause(); api.mockResolvedValueOnce(testPets()); await model.resume()
  expect(api).toHaveBeenCalledTimes(2); expect(model.error.value).toBe('')
  owner = { uid: 202, version: 11, generation: 2 }; model.resetAccount()
  api.mockResolvedValueOnce({ ...testPets(), uid: 202, version: 11 })
  await model.resume()
  expect(api).toHaveBeenCalledTimes(3); expect(model.data.value?.uid).toBe(202)
})

it('返回复用快照后，离页前取消的请求不能覆盖当前数据', async () => {
  const pending = deferred(), api = vi.fn().mockReturnValue(pending.promise)
  const model = usePets(api, () => ({ uid: 101, version: 10, generation: 1 }), () => ({}), vi.fn(), vi.fn())
  model.activate(); model.accept(testPets())
  const old = model.load(); model.pause(); await model.resume()
  expect(api).toHaveBeenCalledTimes(1)
  pending.resolve(testPets(2)); await old
  expect(model.data.value?.total).toBe(1)
})
