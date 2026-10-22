import { computed, onScopeDispose, reactive, ref, shallowRef, watch } from 'vue'
import { parseEggBox, type EggBox, type EggBoxAnnotations, type EggBoxEntry, type EggBoxSaveAnnotations } from '../types/eggBox'

export interface EggBoxHost {
  load: () => Promise<unknown>
  saveAnnotations: (value: EggBoxSaveAnnotations) => Promise<unknown>
  saveFavorite: (value: { uid: number; instance_id: number; favorite: boolean }) => Promise<unknown>
  cancel: () => void
  versionChanged: (version: number) => void
}

interface AnnotationSaveState {
  uid: number
  instanceId: number
  value: EggBoxAnnotations
  pending: EggBoxAnnotations | null
  running: boolean
  error: string
  dirty: boolean
  viewGeneration: number
}

function sameAnnotations(a: EggBoxAnnotations, b: EggBoxAnnotations) {
  return a.nature_id === b.nature_id && a.nest_override === b.nest_override
    && a.note === b.note && a.voice_tag === b.voice_tag && a.voice_db === b.voice_db
}

export function useEggBox(host: EggBoxHost) {
  const data = shallowRef<EggBox | null>(null)
  const loading = ref(false)
  const error = ref('')
  const selectedId = ref<number | null>(null)
  const filters = reactive({ search: '', category: 'all', ascending: false })
  const favoriteOrder = shallowRef(new Set<number>())
  const annotationStates = reactive(new Map<string, AnnotationSaveState>())
  let generation = 0
  let viewGeneration = 0
  let refreshNeeded = false
  const saves = new Set<Promise<void>>()

  function annotationKey(uid: number, instanceId: number) { return `${uid}:${instanceId}` }

  function annotationsFor(egg: EggBoxEntry): EggBoxAnnotations {
    return annotationStates.get(annotationKey(data.value?.uid ?? 0, egg.instance_id))?.value ?? egg.annotations
  }

  function annotationErrorFor(egg: EggBoxEntry): string {
    return annotationStates.get(annotationKey(data.value?.uid ?? 0, egg.instance_id))?.error ?? ''
  }

  function updateAnnotations(uid: number, instanceId: number, value: EggBoxAnnotations) {
    if (data.value?.uid !== uid) return
    const egg = data.value.eggs.find(item => item.instance_id === instanceId)
    if (!egg) return
    const key = annotationKey(uid, instanceId)
    const state = annotationStates.get(key)
    if (state) {
      state.value = { ...value }
      state.dirty = true
    } else {
      annotationStates.set(key, { uid, instanceId, value: { ...value }, pending: null,
        running: false, error: '', dirty: true, viewGeneration })
    }
  }

  async function drainAnnotations(state: AnnotationSaveState) {
    try {
      while (state.pending) {
        const value = state.pending
        state.pending = null
        try {
          await host.saveAnnotations({ uid: state.uid, instance_id: state.instanceId, ...value })
          refreshNeeded = true
          if (sameAnnotations(state.value, value)) state.dirty = false
        } catch (cause) {
          state.pending ??= value
          state.error = cause instanceof Error ? cause.message : String(cause)
          return
        }
      }
    } finally {
      state.running = false
    }
    // 写队列在刷新前释放；过期刷新由 load 的请求代次处理，返回后不再清理草稿。
    if (viewGeneration === state.viewGeneration && data.value?.uid === state.uid) {
      await load()
    }
  }

  function saveAnnotations(uid: number, instanceId: number) {
    if (data.value?.uid !== uid) return
    const egg = data.value.eggs.find(item => item.instance_id === instanceId)
    if (!egg) return
    const state = annotationStates.get(annotationKey(uid, instanceId))
    if (!state || !state.dirty && !state.error) return
    state.pending = { ...state.value }
    state.error = ''
    state.viewGeneration = viewGeneration
    if (state.running) return
    state.running = true
    const task = drainAnnotations(state)
    saves.add(task)
    void task.finally(() => saves.delete(task))
  }

  async function flush() {
    for (const state of annotationStates.values()) {
      if (state.uid === data.value?.uid && state.dirty) saveAnnotations(state.uid, state.instanceId)
    }
    await Promise.all([...saves])
    const failed = [...annotationStates.values()].find(state => state.error)
    if (failed) throw new Error(failed.error)
  }

  const categories = computed(() => {
    const eggs = data.value?.eggs || []
    return [
      { id: 'all', label: '全部', count: eggs.length },
      ...[
        { id: 'regular', label: '普通蛋' }, { id: 'special', label: '特殊蛋' },
        { id: 'shiny', label: '异色蛋' }, { id: 'colorful', label: '炫彩蛋' },
        { id: 'mystery', label: '神奇蛋' }, { id: 'unknown', label: '未收录分类' },
      ].filter(category => category.id !== 'unknown' || eggs.some(egg => egg.egg_kind === 'unknown'))
        .map(category => ({ ...category, count: eggs.filter(egg => egg.egg_kind === category.id).length })),
    ]
  })

  const visibleEggs = computed(() => {
    const keyword = filters.search.trim().toLocaleLowerCase()
    return [...(data.value?.eggs || [])]
      .filter(egg => {
        if (filters.category !== 'all' && egg.egg_kind !== filters.category) return false
        if (!keyword) return true
        return [egg.egg_name, egg.species_name, ...egg.chain_names, String(egg.instance_id), String(egg.egg_conf_id)]
          .some(value => value.toLocaleLowerCase().includes(keyword))
      })
      .sort((a, b) => {
        const byFavorite = Number(favoriteOrder.value.has(b.instance_id))
          - Number(favoriteOrder.value.has(a.instance_id))
        if (byFavorite) return byFavorite
        const byTime = a.obtained_at - b.obtained_at
        const byId = a.instance_id - b.instance_id
        return (filters.ascending ? 1 : -1) * (byTime || byId)
      })
  })

  const selected = computed(() => visibleEggs.value.find(egg => egg.instance_id === selectedId.value) || null)

  watch(visibleEggs, eggs => {
    if (!eggs.some(egg => egg.instance_id === selectedId.value)) selectedId.value = eggs[0]?.instance_id ?? null
  })

  async function load() {
    const current = ++generation
    loading.value = true
    error.value = ''
    try {
      const next = parseEggBox(await host.load())
      if (current !== generation) return
      favoriteOrder.value = new Set(next.eggs.filter(egg => egg.favorite).map(egg => egg.instance_id))
      data.value = next
      refreshNeeded = false
      for (const [key, state] of annotationStates) {
        if (state.running || state.pending || state.error || state.uid !== next.uid) continue
        const egg = next.eggs.find(item => item.instance_id === state.instanceId)
        if (!state.dirty || egg && sameAnnotations(state.value, egg.annotations)) {
          annotationStates.delete(key)
        }
      }
      host.versionChanged(next.version)
      if (!visibleEggs.value.some(egg => egg.instance_id === selectedId.value)) {
        selectedId.value = visibleEggs.value[0]?.instance_id ?? null
      }
    } catch (cause) {
      if (current === generation) error.value = cause instanceof Error ? cause.message : String(cause)
    } finally {
      if (current === generation) loading.value = false
    }
  }

  async function resume(version: number) {
    if (!data.value || data.value.version < version || error.value || refreshNeeded) await load()
  }

  function invalidate() {
    ++generation
    ++viewGeneration
    host.cancel()
    loading.value = false
  }

  function pause() {
    invalidate()
  }

  function resetAccount() {
    pause()
    data.value = null
    selectedId.value = null
    // 切号保留按目标串行的写队列和失败草稿，避免切回同一账号后产生第二个写者。
    filters.category = 'all'
    error.value = ''
  }

  function select(egg: EggBoxEntry) {
    selectedId.value = egg.instance_id
  }

  function setFavorite(instanceId: number, favorite: boolean) {
    if (!data.value?.eggs.some(egg => egg.instance_id === instanceId)) return
    data.value = {
      ...data.value,
      eggs: data.value.eggs.map(egg => egg.instance_id === instanceId ? { ...egg, favorite } : egg),
    }
  }

  function moveSelection(offset: number) {
    const eggs = visibleEggs.value
    if (!eggs.length) return
    const current = eggs.findIndex(egg => egg.instance_id === selectedId.value)
    const next = (Math.max(current, 0) + offset + eggs.length) % eggs.length
    selectedId.value = eggs[next].instance_id
  }

  function clearSelection() {
    selectedId.value = null
  }

  onScopeDispose(pause)
  return { data, loading, error, filters, categories, visibleEggs, selected, selectedId,
    load, resume, pause, resetAccount, select, setFavorite, moveSelection, clearSelection,
    annotationsFor, annotationErrorFor, updateAnnotations, saveAnnotations, flush }
}
