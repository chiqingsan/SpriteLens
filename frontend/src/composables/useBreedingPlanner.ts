import { computed, reactive, ref, watch } from 'vue'
import { parseContext, parseResult, parseSaved, type Draft, type Mode, type Placement, type Plan, type PlannerContext, type Result } from '../types/breedingPlanner'

export interface PlannerHost {
  request(path: string, body?: unknown): Promise<unknown | null>
  cancel(): void; context(): { uid: number | null; version: number; generation: number }; openPet(gid: string): void
}
function empty(mode: Mode): Draft {
  return { mode, goals: [], selected: [], participation: 'best', capacity: 10, academy: false, placements: [], approved: [],
    rule_version: 'planner-dual-mark-v1', geometry_version: 'community-grid-v1' }
}
const copy = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T
// 只比较用户可编辑字段，用于判断当前入口草稿是否有未保存的修改。
function snapshotKey(value: Draft) {
  return JSON.stringify([value.goals, value.selected, [...value.approved].sort(), value.participation, value.capacity, value.academy,
    [...value.placements].sort((a, b) => a.gid.localeCompare(b.gid)).map(p => [p.gid, p.x, p.y, p.kind, p.lock, p.primary_goal_id])])
}

export function useBreedingPlanner(host: PlannerHost) {
  const context = ref<PlannerContext | null>(null), mode = ref<Mode>('target')
  const drafts = reactive({ target: empty('target'), selected: empty('selected') })
  const results = reactive<Record<Mode, Result | null>>({ target: null, selected: null })
  const active = reactive<Record<Mode, number>>({ target: 0, selected: 0 })
  const originals = reactive<Record<Mode, Plan[]>>({ target: [], selected: [] })
  const dirty = reactive({ target: false, selected: false }), edited = reactive({ target: false, selected: false })
  const history: Record<Mode, Placement[][]> = { target: [], selected: [] }, future: Record<Mode, Placement[][]> = { target: [], selected: [] }
  const solvedInputs: Record<Mode, string> = { target: '', selected: '' }
  const restored = { target: false, selected: false }
  const historyRevision = ref(0), busy = ref(''), error = ref(''), notice = ref(''), revision = ref(0), errorAction = ref<'' | 'save' | 'load'>('')
  const savedKeys = reactive<Record<Mode, string>>({ target: '', selected: '' })
  let generation = 0, loadedUid: number | null = null, suppress = false
  const draft = computed(() => drafts[mode.value]), result = computed(() => results[mode.value])
  const plan = computed(() => result.value?.plans[active[mode.value]] || null)
  const parents = computed(() => new Map(context.value?.parents.map(p => [p.gid, p]) || []))
  const canGenerate = computed(() => !!context.value?.available && context.value.uid > 0 && !busy.value && (mode.value === 'target' ? draft.value.goals.length > 0 : draft.value.selected.length > 0))
  const canUndo = computed(() => (historyRevision.value, history[mode.value].length > 0))
  const canRedo = computed(() => (historyRevision.value, future[mode.value].length > 0))
  const canRestore = computed(() => edited[mode.value] && !!originals[mode.value][active[mode.value]])
  const unsaved = computed(() => !!context.value?.uid && restored[mode.value] && snapshotKey(drafts[mode.value]) !== savedKeys[mode.value])
  watch(drafts, () => {
    if (suppress) return
    restored[mode.value] = true
    revision.value++; dirty[mode.value] = true; notice.value = ''
    generation++; host.cancel(); busy.value = ''
  }, { deep: true, flush: 'sync' })

  function body() { return { ...copy(draft.value), uid: context.value?.uid, version: context.value?.version,
    catalog_version: context.value?.catalog_version, revision: revision.value } }
  function current(ticket: number, uid: number | undefined) { return ticket === generation && host.context().uid === uid }
  async function load(force = false) {
    const outer = host.context()
    if (!force && context.value && context.value.uid === outer.uid && context.value.version === outer.version && restored.target && restored.selected) return
    pause()
    const ticket = ++generation
    busy.value = 'loading'; error.value = ''; errorAction.value = ''
    try {
      const response = await host.request('context')
      if (!response || ticket !== generation) return
      const data = parseContext(response)
      if (host.context().uid !== data.uid) return
      context.value = data
      if (loadedUid !== data.uid || !restored.target || !restored.selected) {
        loadedUid = data.uid
        for (const entry of ['target', 'selected'] as const) {
          if (restored[entry]) continue
          const saved = await host.request(`draft?mode=${entry}`)
          if (!saved || !current(ticket, data.uid)) return
          const payload = saved as { draft: unknown; error?: string }
          if (payload.error) error.value = payload.error
          if (payload.draft) {
            const restored = parseSaved(payload.draft)
            suppress = true; drafts[entry] = copy(restored); suppress = false
            dirty[entry] = true
          }
          restored[entry] = true
          savedKeys[entry] = snapshotKey(drafts[entry])
        }
        notice.value = draft.value.placements.length ? '已恢复原亲本和布局，点击「重评布局」按当前目录与规则核对记录。' : ''
        if (draft.value.rule_version !== data.rule_version || draft.value.geometry_version !== data.geometry_version) notice.value = '规则版本已变化，原亲本和坐标保留；点击重评后按当前模拟规则重新分析。'
      } else {
        dirty.target = true; dirty.selected = true
        notice.value = '背包记录已更新，现有布局保留；请重评或重新规划。'
      }
    } catch (e) { if (ticket === generation) { error.value = (e as Error).message; errorAction.value = 'load' } }
    finally { if (ticket === generation) busy.value = '' }
  }
  // 只重新读取背包资料，保留本地未保存的草稿编辑，用于「刷新资料」重试。
  async function refresh() {
    const ticket = ++generation
    busy.value = 'loading'; error.value = ''; errorAction.value = ''
    try {
      const response = await host.request('context')
      if (!response || ticket !== generation) return
      const data = parseContext(response)
      if (host.context().uid !== data.uid) return
      context.value = data
      notice.value = unsaved.value ? '已刷新背包资料；本地未保存的修改仍保留。' : '已刷新背包资料。'
    } catch (e) { if (ticket === generation) { error.value = (e as Error).message; errorAction.value = 'load' } }
    finally { if (ticket === generation) busy.value = '' }
  }
  async function run(action: 'solve' | 'evaluate') {
    if (!context.value) return
    if (action === 'solve' && mode.value === 'target') {
      const unique = new Map<string, typeof draft.value.goals[number]>(), aliases = new Map<string, string>()
      for (const goal of draft.value.goals) {
        const key = JSON.stringify([goal.egg_key, goal.size_mark, goal.voice_mark, goal.nature_id, goal.priority])
        const existing = unique.get(key)
        if (existing) aliases.set(goal.goal_id, existing.goal_id)
        else unique.set(key, goal)
      }
      if (aliases.size) {
        suppress = true
        draft.value.goals = [...unique.values()]
        draft.value.placements.forEach(p => { p.primary_goal_id = aliases.get(p.primary_goal_id) || p.primary_goal_id })
        draft.value.approved = [...new Set(draft.value.approved.map(key => { const [goal, ...pair] = key.split(':'); return [aliases.get(goal!) || goal, ...pair].join(':') }))]
        suppress = false; revision.value++
      }
    }
    const snapshot = { ...body(), rule_version: context.value.rule_version, geometry_version: context.value.geometry_version }, ticket = ++generation, entry = mode.value
    busy.value = action; error.value = ''; notice.value = ''; errorAction.value = ''
    const previous = copy(plan.value)
    const inputKey = JSON.stringify([snapshot.goals, snapshot.capacity, snapshot.academy, snapshot.selected, snapshot.participation])
    try {
      const response = await host.request(action, snapshot)
      if (!response || !current(ticket, snapshot.uid) || snapshot.revision !== revision.value) return
      const data = parseResult(response)
      if (data.revision !== snapshot.revision || data.version !== snapshot.version || host.context().version !== data.version) return
      // 允许迭代后重新规划时，保留旧合格方案作为比较项。
      const comparison = results[entry]?.plans.find(p => p.plan_id === 'previous') || previous
      if (action === 'solve' && snapshot.approved.length && comparison?.goals.some(g => g.exact_mothers > 0) && solvedInputs[entry] === inputKey) {
        const layoutKey = (p: Plan) => JSON.stringify([p.placements.map(pos => [pos.gid, pos.kind]).sort(), p.edges.map(e => [e.male, e.female]).sort()])
        if (!data.plans.some(p => layoutKey(p) === layoutKey(comparison))) data.plans = [...data.plans.slice(0, 2), { ...comparison, plan_id: 'previous' }]
      }
      const assessed = data.plans[0]
      if (action === 'evaluate' && results[entry]) {
        const previousResult = results[entry]!
        data.iterations = previousResult.iterations
        const plans = [...previousResult.plans]
        if (assessed) plans[active[entry]] = { ...assessed, plan_id: previous?.plan_id || 'adjusted' }
        data.plans = plans
      } else active[entry] = 0
      results[entry] = data
      if (assessed && assessed.status !== 'invalid') {
        suppress = true; drafts[entry].placements = copy(assessed.placements)
        drafts[entry].rule_version = snapshot.rule_version; drafts[entry].geometry_version = snapshot.geometry_version; suppress = false
      }
      dirty[entry] = false; edited[entry] = action === 'evaluate'
      if (action === 'solve') { originals[entry] = copy(data.plans); solvedInputs[entry] = inputKey; history[entry] = []; future[entry] = []; historyRevision.value++ }
    } catch (e) { if (ticket === generation) error.value = (e as Error).message }
    finally { if (ticket === generation) busy.value = '' }
  }
  async function save() {
    const snapshot = body(), ticket = ++generation, entry = mode.value
    busy.value = 'saving'; error.value = ''; errorAction.value = ''
    try {
      const response = await host.request('draft', snapshot)
      if (response && current(ticket, snapshot.uid)) { savedKeys[entry] = snapshotKey(snapshot); notice.value = '当前入口草稿已保存。' }
    } catch (e) { if (ticket === generation) { error.value = (e as Error).message; errorAction.value = 'save' } }
    finally { if (ticket === generation) busy.value = '' }
  }
  function changeMode(value: Mode) { pause(); mode.value = value; error.value = ''; notice.value = ''; void load() }
  function pause() { generation++; host.cancel(); busy.value = '' }
  function resetAccount() {
    pause(); suppress = true
    for (const entry of ['target', 'selected'] as const) {
      drafts[entry] = empty(entry); results[entry] = null; active[entry] = 0
      dirty[entry] = false; edited[entry] = false; history[entry] = []; future[entry] = []
      solvedInputs[entry] = ''
      originals[entry] = []
      restored[entry] = false
      savedKeys[entry] = ''
    }
    suppress = false; context.value = null; loadedUid = null; error.value = ''; notice.value = ''; errorAction.value = ''; historyRevision.value++
  }
  function edit(positions: Placement[]) {
    history[mode.value].push(copy(draft.value.placements)); future[mode.value] = []
    if (history[mode.value].length > 40) history[mode.value].shift()
    draft.value.placements = copy(positions); edited[mode.value] = true; historyRevision.value++
    void run('evaluate')
  }
  function undo(redo = false) {
    const source = redo ? future[mode.value] : history[mode.value], destination = redo ? history[mode.value] : future[mode.value]
    const positions = source.pop()
    if (!positions) return
    destination.push(copy(draft.value.placements)); draft.value.placements = positions; historyRevision.value++; void run('evaluate')
  }
  function choosePlan(index: number) {
    const chosen = result.value?.plans[index]
    if (!chosen) return
    if (draft.value.placements.some(old => old.lock && !chosen.placements.some(p => p.gid === old.gid && (old.lock !== 'position' || p.x === old.x && p.y === old.y && p.kind === old.kind)))) {
      error.value = '此备选不满足当前锁定，请先解除冲突。'; return
    }
    active[mode.value] = index; edit(chosen.placements)
  }
  function restorePlan() {
    const original = originals[mode.value][active[mode.value]]
    if (!original) return
    if (draft.value.placements.some(old => old.lock && !original.placements.some(p => p.gid === old.gid && (old.lock !== 'position' || p.x === old.x && p.y === old.y && p.kind === old.kind)))) {
      error.value = '原布局与当前锁定冲突，请先解除相关锁定。'; return
    }
    edit(original.placements)
  }
  function clearPlan() {
    pause()
    suppress = true
    drafts[mode.value].placements = []
    results[mode.value] = null
    active[mode.value] = 0
    dirty[mode.value] = false
    edited[mode.value] = false
    originals[mode.value] = []
    history[mode.value] = []
    future[mode.value] = []
    solvedInputs[mode.value] = ''
    suppress = false
    historyRevision.value++
    revision.value++
    notice.value = ''
    error.value = ''
    errorAction.value = ''
  }
  return { context, mode, draft, result, plan, parents, dirty, edited, busy, error, errorAction, notice, revision, unsaved,
    canGenerate, canUndo, canRedo, canRestore, load, refresh, run, save, changeMode, pause, resetAccount, edit, undo, choosePlan, restorePlan, clearPlan }
}
