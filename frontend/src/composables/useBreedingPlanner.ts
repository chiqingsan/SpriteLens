import { computed, onScopeDispose, reactive, ref, watch } from 'vue'
import { parseContext, parseResult, parseSaved, type Draft, type Mode, type Placement, type Plan, type PlannerContext, type Result } from '../types/breedingPlanner'

export interface PlannerHost {
  request(path: string, body?: unknown): Promise<unknown | null>
  cancel(): void; context(): { uid: number | null; version: number; generation: number }; openPet(gid: string): void
  confirmOverwrite?(): boolean
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

// 草稿改动后静默落盘的防抖间隔；取小值，避免「改完立刻关掉软件」时最后一次改动丢失。
const AUTOSAVE_DELAY = 150
// 自动保存请求被取消时的有界重试次数。每次草稿改动都会 host.cancel() 在途请求，
// 若把空响应当作「已保存」直接返回，改动会静默丢失（关掉软件再打开又变回原样）。
const AUTOSAVE_RETRIES = 3

export function useBreedingPlanner(host: PlannerHost) {
  const context = ref<PlannerContext | null>(null), mode = ref<Mode>('target')
  const drafts = reactive({ target: empty('target'), selected: empty('selected') })
  const results = reactive<Record<Mode, Result | null>>({ target: null, selected: null })
  const active = reactive<Record<Mode, number>>({ target: 0, selected: 0 })
  const originals = reactive<Record<Mode, Plan[]>>({ target: [], selected: [] })
  const dirty = reactive({ target: false, selected: false }), edited = reactive({ target: false, selected: false })
  const history: Record<Mode, Placement[][]> = { target: [], selected: [] }, future: Record<Mode, Placement[][]> = { target: [], selected: [] }
  const solvedInputs: Record<Mode, string> = { target: '', selected: '' }
  const restored = reactive({ target: false, selected: false })
  const historyRevision = ref(0), busy = ref(''), error = ref(''), notice = ref(''), revision = ref(0), errorAction = ref<'' | 'save' | 'load'>('')
  const savedKeys = reactive<Record<Mode, string>>({ target: '', selected: '' })
  const savedRevisions: Record<Mode, number> = { target: 0, selected: 0 }
  const conflicts: Record<Mode, number | null> = { target: null, selected: null }
  const saveQueues: Record<Mode, Promise<void>> = { target: Promise.resolve(), selected: Promise.resolve() }
  let generation = 0, loadedUid: number | null = null, suppress = false
  let autoTimer: ReturnType<typeof setTimeout> | null = null, autoSaving = false, autoPending = false, autoRetry = 0
  const draft = computed(() => drafts[mode.value]), result = computed(() => results[mode.value])
  const plan = computed(() => result.value?.plans[active[mode.value]] || null)
  const parents = computed(() => new Map(context.value?.parents.map(p => [p.gid, p]) || []))
  const canGenerate = computed(() => !!context.value?.available && context.value.uid > 0 && !busy.value && (mode.value === 'target' ? draft.value.goals.length > 0 : draft.value.selected.length > 0))
  const canUndo = computed(() => (historyRevision.value, history[mode.value].length > 0))
  const canRedo = computed(() => (historyRevision.value, future[mode.value].length > 0))
  const canRestore = computed(() => edited[mode.value] && !!originals[mode.value][active[mode.value]])
  // 注意：必须先读草稿再判断，否则组件首次渲染时（restored 还是 false）会短路掉对 drafts 的依赖，
  // 此后草稿怎么改 unsaved 都恒为 false：保存按钮永久禁用、自动保存永不触发（改动全部只在内存里）。
  const unsaved = computed(() => {
    const key = snapshotKey(drafts[mode.value])
    if (!context.value?.uid || !restored[mode.value]) return false
    return key !== savedKeys[mode.value]
  })
  watch(drafts, () => {
    if (suppress) return
    restored[mode.value] = true
    revision.value++; dirty[mode.value] = true; notice.value = ''
    generation++; host.cancel(); busy.value = ''
    scheduleAutosave()
  }, { deep: true, flush: 'sync' })

  function bodyFor(entry: Mode) { return { ...copy(drafts[entry]), uid: context.value?.uid, version: context.value?.version,
    catalog_version: context.value?.catalog_version, revision: revision.value } }
  function body() { return bodyFor(mode.value) }
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
            const savedDraft = parseSaved(payload.draft)
            suppress = true; drafts[entry] = copy(savedDraft); suppress = false
            dirty[entry] = true
            const savedRevision = (payload.draft as { revision?: unknown }).revision
            if (typeof savedRevision === 'number' && Number.isSafeInteger(savedRevision)) {
              revision.value = Math.max(revision.value, savedRevision)
              savedRevisions[entry] = savedRevision
            }
          }
          restored[entry] = true
          savedKeys[entry] = snapshotKey(drafts[entry])
        }
        // 恢复提示要覆盖「只有目标、没有窝位」的草稿：否则目标卡会凭空出现、没有任何解释。
        notice.value = draft.value.placements.length
          ? '已恢复原亲本和布局，点击「重评布局」按当前目录与规则核对记录。'
          : draft.value.goals.length
            ? `已恢复上次保存的 ${draft.value.goals.length} 个培育目标；如需从空白开始，移除目标后点「保存草稿」。`
            : ''
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
    // 规划期间不动提示条：提示条的出现/消失会把工具条与画布顶下/顶上，属 UI 跳动。
    busy.value = action; error.value = ''; errorAction.value = ''
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
    finally { if (ticket === generation) { busy.value = ''; if (unsaved.value) scheduleAutosave() } }
  }
  function persist(entry: Mode, snapshot: ReturnType<typeof body>) {
    const task = saveQueues[entry].then(async () => {
      if (context.value?.uid !== snapshot.uid) throw new Error('账号已变化，旧草稿未保存。')
      if (conflicts[entry] !== null) throw new Error('另一窗口已修改草稿；点击「保存草稿」确认是否覆盖。')
      const base = savedRevisions[entry]
      const response = await host.request('draft', { ...snapshot, base_revision: base,
        revision: Math.max(snapshot.revision, base + 1) })
      if (!response) throw new Error('草稿保存被中断，请重试。')
      if (context.value?.uid !== snapshot.uid) return
      const value = response as { saved?: boolean; revision?: number }
      if (value.saved === false) {
        conflicts[entry] = value.revision ?? base
        throw new Error('另一窗口已修改草稿；点击「保存草稿」确认是否覆盖。')
      }
      savedRevisions[entry] = value.revision ?? Math.max(snapshot.revision, base + 1)
      savedKeys[entry] = snapshotKey(snapshot)
    })
    saveQueues[entry] = task.catch(() => {}) // 失败由调用者显示，后续显式重试仍可排队。
    return task
  }
  async function save() {
    const entry = mode.value
    if (conflicts[entry] !== null) {
      if (!host.confirmOverwrite?.()) return
      savedRevisions[entry] = conflicts[entry]!
      conflicts[entry] = null
    }
    const snapshot = body(), ticket = ++generation
    busy.value = 'saving'; error.value = ''; errorAction.value = ''
    try {
      await persist(entry, snapshot)
      if (current(ticket, snapshot.uid)) notice.value = '当前入口草稿已保存。'
    } catch (e) { if (ticket === generation) { error.value = (e as Error).message; errorAction.value = 'save' } }
    finally { if (ticket === generation) busy.value = '' }
  }
  /**
   * 草稿改动后自动落盘：静默（不占 busy、不写提示条），
   * 否则「移除目标 / 加目标」这类改动只在内存里，关掉软件再进来又变回原样。
   */
  function scheduleAutosave() {
    autoRetry = 0
    if (autoTimer !== null) clearTimeout(autoTimer)
    autoTimer = setTimeout(() => { autoTimer = null; void autosave() }, AUTOSAVE_DELAY)
  }
  async function autosave() {
    if (autoSaving) { autoPending = true; return }
    autoSaving = true
    try {
      do {
        autoPending = false
        if (busy.value || !context.value?.uid || !unsaved.value) return
        const snapshot = body(), entry = mode.value, uid = context.value.uid
        try {
          await persist(entry, snapshot)
        } catch (cause) {
          if (context.value?.uid !== uid) return
          if ((cause as Error).message.includes('被中断') && autoRetry < AUTOSAVE_RETRIES) {
            autoRetry++
            if (autoTimer !== null) clearTimeout(autoTimer)
            autoTimer = setTimeout(() => { autoTimer = null; void autosave() }, AUTOSAVE_DELAY)
            return
          }
          throw cause
        }
        if (context.value?.uid !== uid) return
        autoRetry = 0
      } while (autoPending)
    } catch (e) { error.value = (e as Error).message; errorAction.value = 'save' }
    finally { autoSaving = false }
  }
  /** 原生关闭握手等待服务端确认，两个入口都保存后才允许退出。 */
  async function flush() {
    if (autoTimer !== null) { clearTimeout(autoTimer); autoTimer = null }
    if (!context.value?.uid) return
    try {
      for (const entry of ['target', 'selected'] as const) {
        await saveQueues[entry]
        if (!restored[entry]) continue
        const snapshot = bodyFor(entry)
        if (snapshotKey(snapshot) !== savedKeys[entry]) await persist(entry, snapshot)
      }
      if (errorAction.value === 'save') { error.value = ''; errorAction.value = '' }
    } catch (cause) {
      error.value = (cause as Error).message; errorAction.value = 'save'
      throw cause
    }
  }
  onScopeDispose(() => {
    if (autoTimer !== null) { clearTimeout(autoTimer); autoTimer = null; void autosave() }
  })
  function changeMode(value: Mode) { pause(); mode.value = value; error.value = ''; notice.value = ''; void load() }
  /** 暂停当前入口；flush 为真时把待写的自动保存补一次（清空方案时先清空再落盘，不写旧草稿）。 */
  function pause(flush = true) {
    generation++; host.cancel(); busy.value = ''
    if (autoTimer !== null) { clearTimeout(autoTimer); autoTimer = null; if (flush) void autosave() }
  }
  function resetAccount() {
    pause(); suppress = true
    for (const entry of ['target', 'selected'] as const) {
      drafts[entry] = empty(entry); results[entry] = null; active[entry] = 0
      dirty[entry] = false; edited[entry] = false; history[entry] = []; future[entry] = []
      solvedInputs[entry] = ''
      originals[entry] = []
      restored[entry] = false
      savedKeys[entry] = ''
      savedRevisions[entry] = 0; conflicts[entry] = null
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
  /** 清除方案：清空画布预览与培育目标（自选模式保留参与精灵），并把清空结果落盘。 */
  function clearPlan() {
    pause(false)
    const cleared = drafts[mode.value]
    suppress = true
    cleared.placements = []
    cleared.goals = []
    cleared.approved = []
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
    notice.value = mode.value === 'target' ? '已清除当前方案与培育目标。' : '已清除当前方案。'
    error.value = ''
    errorAction.value = ''
    scheduleAutosave()
  }
  return { context, mode, draft, result, plan, parents, dirty, edited, busy, error, errorAction, notice, revision, unsaved,
    canGenerate, canUndo, canRedo, canRestore, load, refresh, run, save, flush, changeMode, pause, resetAccount, edit, undo, choosePlan, restorePlan, clearPlan }
}
