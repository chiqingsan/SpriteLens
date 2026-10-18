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
// 自动保存是 150ms 防抖（失败重试会再等一轮），测试等它落地。
const AUTOSAVE_WAIT = 500
const settle = (ms = AUTOSAVE_WAIT) => new Promise(resolve => setTimeout(resolve, ms))
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
  it('恢复只有目标、没有窝位的草稿时也给出可见提示', async () => {
    const { model, host, stop } = setup()
    const draft = { ...model.draft.value, placements: [],
      goals: [{ goal_id: 'goal-1', egg_key: '大耳帽兜#3121001', size_mark: '', voice_mark: '', nature_id: 0, priority: 0 }] }
    vi.mocked(host.request).mockResolvedValueOnce(context()).mockResolvedValueOnce({ draft }).mockResolvedValueOnce({ draft: null })
    await model.load()
    expect(model.draft.value.goals.length).toBe(1)
    expect(model.notice.value).toContain('已恢复上次保存的 1 个培育目标')
    stop()
  })
  it('移除目标后自动落盘，不需要手动点保存草稿', async () => {
    const { model, host, stop } = setup()
    const draft = { ...model.draft.value, placements: [],
      goals: [{ goal_id: 'goal-1', egg_key: '大耳帽兜#3121001', size_mark: '', voice_mark: '', nature_id: 0, priority: 0 }] }
    vi.mocked(host.request).mockResolvedValueOnce(context()).mockResolvedValueOnce({ draft }).mockResolvedValueOnce({ draft: null })
    await model.load()
    expect(model.unsaved.value).toBe(false)
    vi.mocked(host.request).mockClear()
    model.draft.value.goals = []
    expect(model.unsaved.value).toBe(true)
    await settle()
    const saved = vi.mocked(host.request).mock.calls.find(call => call[0] === 'draft')
    expect(saved, '草稿改动后应自动写回').toBeTruthy()
    expect((saved![1] as { goals: unknown[] }).goals).toEqual([])
    expect(model.unsaved.value).toBe(false)
    expect(model.notice.value).not.toContain('已保存')
    expect(model.busy.value).toBe('')
    stop()
  })
  it('自动保存失败时保留草稿并给出可重试的错误', async () => {
    const { model, host, stop } = setup()
    await model.load()
    vi.mocked(host.request).mockRejectedValueOnce(new Error('磁盘只读'))
    model.draft.value.capacity = 8
    await settle()
    expect(model.error.value).toBe('磁盘只读')
    expect(model.errorAction.value).toBe('save')
    expect(model.draft.value.capacity).toBe(8)
    stop()
  })
  it('自动保存请求被取消时重试，不把改动静默丢掉', async () => {
    const { model, host, stop } = setup()
    const draft = { ...model.draft.value, placements: [],
      goals: [{ goal_id: 'goal-1', egg_key: '大耳帽兜#3121001', size_mark: '', voice_mark: '', nature_id: 0, priority: 0 }] }
    vi.mocked(host.request).mockResolvedValueOnce(context()).mockResolvedValueOnce({ draft }).mockResolvedValueOnce({ draft: null })
    await model.load()
    vi.mocked(host.request).mockClear()
    // host.cancel() 打断在途请求时的既有语义：request 解析为 null。
    vi.mocked(host.request).mockResolvedValueOnce(null)
    model.draft.value.goals = []
    await settle()
    const attempts = vi.mocked(host.request).mock.calls.filter(call => call[0] === 'draft')
    expect(attempts.length, '被取消的自动保存必须重试，不能当作已保存').toBeGreaterThan(1)
    expect(model.unsaved.value).toBe(false)
    stop()
  })
  it('关窗（pagehide）时用 keepalive 请求兜底落盘', async () => {
    const { model, host, stop } = setup()
    await model.load()
    const flush = vi.fn(() => true); host.flush = flush
    model.draft.value.capacity = 9
    window.dispatchEvent(new Event('pagehide'))
    expect(flush).toHaveBeenCalledWith('draft', expect.objectContaining({ capacity: 9 }))
    expect(model.unsaved.value).toBe(false)
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
  it('清除方案清空预览与培育目标，并把清空结果落盘', async () => {
    const { model, host, stop } = setup()
    const goal = { goal_id: 'goal-1', egg_key: 'egg-a', size_mark: '', voice_mark: '', nature_id: 0, priority: false }
    vi.mocked(host.request).mockImplementation(async path => path === 'context' ? context(101)
      : path === 'draft?mode=target'
        ? { uid: 101, version: 1, draft: { ...model.draft.value, goals: [goal], placements: positions } }
        : { uid: 101, version: 1, draft: null })
    await model.load()
    expect(model.draft.value.goals).toHaveLength(1)
    expect(model.unsaved.value).toBe(false)
    vi.mocked(host.request).mockClear()
    vi.mocked(host.request).mockImplementation(async () => ({ uid: 101, version: 1, draft: null }))
    model.clearPlan()
    expect(model.draft.value.placements).toEqual([])
    expect(model.draft.value.goals).toEqual([])
    expect(model.result.value).toBeNull()
    expect(model.draft.value.capacity).toBe(10)
    expect(model.dirty.target).toBe(false)
    expect(model.notice.value).toContain('已清除当前方案与培育目标')
    await settle(300)
    const drafts = vi.mocked(host.request).mock.calls.filter(call => call[0] === 'draft')
    expect(drafts.length, '清除方案必须落盘，否则重启后目标蛋又回来').toBeGreaterThan(0)
    expect((drafts[drafts.length - 1]![1] as { goals: unknown[] }).goals).toEqual([])
    expect(model.unsaved.value).toBe(false)
    stop()
  })
  it('保存成功后清除未保存标记，继续修改会重新标记', async () => {
    const { model, stop } = setup(); await model.load()
    expect(model.unsaved.value).toBe(false)
    model.draft.value.capacity = 6
    expect(model.unsaved.value).toBe(true)
    await model.save()
    expect(model.unsaved.value).toBe(false)
    expect(model.error.value).toBe('')
    expect(model.errorAction.value).toBe('')
    model.draft.value.capacity = 7
    expect(model.unsaved.value).toBe(true)
    stop()
  })
  it('保存失败标为可重试并保留本地编辑，刷新资料不清空草稿', async () => {
    const { model, host, stop } = setup(); await model.load()
    model.draft.value.capacity = 6
    const before = JSON.stringify(model.draft.value)
    vi.mocked(host.request).mockRejectedValueOnce(new Error('草稿保存失败：磁盘只读'))
    await model.save()
    expect(model.errorAction.value).toBe('save')
    expect(model.error.value).toBe('草稿保存失败：磁盘只读')
    expect(JSON.stringify(model.draft.value)).toBe(before)
    expect(model.unsaved.value).toBe(true)
    vi.mocked(host.request).mockResolvedValueOnce(context())
    await model.refresh()
    expect(model.context.value?.uid).toBe(101)
    expect(JSON.stringify(model.draft.value)).toBe(before)
    expect(model.unsaved.value).toBe(true)
    expect(model.error.value).toBe('')
    stop()
  })
  it('撤销与重做在两次窝位调整之间往返', async () => {
    const { model, host, stop } = setup(); await model.load()
    vi.mocked(host.request).mockImplementation(async (_path, body) => {
      const snapshot = body as { revision: number; placements: unknown }
      const base = result(snapshot.revision)
      return { ...base, plans: [{ ...base.plans[0]!, placements: snapshot.placements }] }
    })
    model.draft.value.goals = [{ goal_id: 'goal-1', egg_key: 'egg-a', size_mark: '', voice_mark: '', nature_id: 0, priority: false }]
    model.draft.value.placements = positions
    await model.run('solve')
    model.edit([{ ...positions[0]!, x: 4 }]); await Promise.resolve(); await Promise.resolve()
    expect(model.draft.value.placements[0]?.x).toBe(4)
    expect(model.canUndo.value).toBe(true)
    model.undo(); await Promise.resolve(); await Promise.resolve()
    expect(model.draft.value.placements[0]?.x).toBe(0)
    expect(model.canRedo.value).toBe(true)
    model.undo(true); await Promise.resolve(); await Promise.resolve()
    expect(model.draft.value.placements[0]?.x).toBe(4)
    expect(model.canRedo.value).toBe(false)
    stop()
  })
})
