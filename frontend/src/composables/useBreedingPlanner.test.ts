import { effectScope } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { useBreedingPlanner, type PlannerHost } from './useBreedingPlanner'
import { parseResult, type Placement, type PlannerContext, type Result } from '../types/breedingPlanner'

const context = (uid = 101): PlannerContext => ({ uid, version: 1, available: true, source: 'observed', pet_count: 2,
  parents: [], eggs: [], natures: [], issues: [], rule_version: 'planner-dual-mark-v1', geometry_version: 'community-grid-v1', catalog_version: 'synthetic' })
const positions: Placement[] = [{ gid: '9223372036854775809', x: 0, y: 0, kind: 'normal', lock: '', primary_goal_id: '' }]
const result = (revision: number): Result => ({ uid: 101, version: 1, revision, status: 'no_plan', search_status: 'bounded', issues: [], iterations: [],
  plans: [{ plan_id: 'plan-1', status: 'no_plan', placements: positions, edges: [], mothers: [], goals: [], metrics: {}, issues: [], unused_candidates: [] },
    { plan_id: 'plan-2', status: 'no_plan', placements: [{ ...positions[0]!, gid: '2', x: 2 }], edges: [], mothers: [], goals: [], metrics: {}, issues: [], unused_candidates: [] }] })
function deferred() { let resolve!: (value: unknown) => void; const promise = new Promise<unknown>(r => { resolve = r }); return { promise, resolve } }
function setup() {
  let uid = 101
  const host: PlannerHost = { request: vi.fn(async path => path === 'context' ? context(uid) : { uid, version: 1, draft: null }),
    cancel: vi.fn(), context: () => ({ uid, version: 1, generation: 1 }), openPet: vi.fn() }
  const scope = effectScope(), model = scope.run(() => useBreedingPlanner(host))!
  return { model, host, stop: () => scope.stop(), switchUid: () => { uid = 202 } }
}
describe('配窝请求、恢复和编辑边界', () => {
  it('输入变化和切号使在途求解失效', async () => {
    const { model, host, stop, switchUid } = setup()
    await model.load()
    const pending = deferred(); vi.mocked(host.request).mockReturnValueOnce(pending.promise)
    const task = model.run('solve'), revision = model.revision.value
    model.draft.value.capacity = 5
    pending.resolve(result(revision)); await task
    expect(model.result.value).toBeNull()
    const old = deferred(); vi.mocked(host.request).mockReturnValueOnce(old.promise)
    const second = model.run('solve'); switchUid(); model.resetAccount()
    old.resolve(result(model.revision.value)); await second
    expect(model.result.value).toBeNull(); expect(model.draft.value.placements).toEqual([])
    stop()
  })
  it('恢复真实大整数ID，不自动重新求解或替换失踪亲本', async () => {
    const { model, host, stop } = setup()
    const draft = { ...model.draft.value, placements: positions }
    vi.mocked(host.request).mockResolvedValueOnce(context()).mockResolvedValueOnce({ draft }).mockResolvedValueOnce({ draft: null })
    await model.load()
    expect(model.draft.value.placements[0]?.gid).toBe('9223372036854775809')
    expect(model.dirty.target).toBe(true)
    expect(vi.mocked(host.request).mock.calls.map(c => c[0])).toEqual(['context', 'draft?mode=target', 'draft?mode=selected'])
    stop()
  })
  it('重评保留备选和身份，撤销恢复坐标，保存失败保留草稿', async () => {
    const { model, host, stop } = setup(); await model.load()
    vi.mocked(host.request).mockImplementation(async (_path, body) => result((body as { revision: number }).revision))
    await model.run('solve'); model.choosePlan(1)
    await Promise.resolve(); await Promise.resolve()
    expect(model.result.value?.plans.length).toBe(2)
    expect(model.plan.value?.plan_id).toBe('plan-2')
    model.edit([{ ...positions[0]!, x: 4 }]); await Promise.resolve(); await Promise.resolve()
    model.undo(); await Promise.resolve(); await Promise.resolve()
    expect(model.draft.value.placements[0]?.x).toBe(0)
    vi.mocked(host.request).mockRejectedValueOnce(new Error('磁盘已满'))
    const before = JSON.stringify(model.draft.value); await model.save()
    expect(model.error.value).toBe('磁盘已满'); expect(JSON.stringify(model.draft.value)).toBe(before)
    stop()
  })
  it('两个入口保持独立草稿，拒绝缺少权威布局的响应', async () => {
    const { model, stop } = setup(); await model.load()
    model.draft.value.capacity = 6; model.changeMode('selected'); model.draft.value.selected = ['123']
    model.changeMode('target'); expect(model.draft.value.capacity).toBe(6)
    model.changeMode('selected'); expect(model.draft.value.selected).toEqual(['123'])
    expect(() => parseResult({ ...result(1), plans: [{ ...result(1).plans[0], placements: [{ gid: 1 }] }] })).toThrow()
    stop()
  })
  it('清除当前方案并保留培育配置', async () => {
    const { model, host, stop } = setup(); await model.load()
    model.draft.value.goals = [{ goal_id: 'goal-1', egg_key: 'egg-a', size_mark: '', voice_mark: '', nature_id: 0, priority: false }]
    model.draft.value.placements = positions
    vi.mocked(host.request).mockImplementation(async (_path, body) => result((body as { revision: number }).revision))
    await model.run('solve')
    model.clearPlan()
    expect(model.draft.value.placements).toEqual([])
    expect(model.result.value).toBeNull()
    expect(model.draft.value.goals).toHaveLength(1)
    expect(model.draft.value.capacity).toBe(10)
    expect(model.dirty.target).toBe(false)
    stop()
  })
})
