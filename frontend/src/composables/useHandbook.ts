import { onScopeDispose, reactive, ref, shallowRef, watch } from 'vue'
import type { ApiClient } from '../api/client'
import { parseHandbook, type Handbook, type HandbookSort } from '../types/handbook'

export type HandbookFilters = {
  search: string
  type: string
  stage: number
  eggGroup: string
  sort: HandbookSort
}
const DEFAULTS: HandbookFilters = { search: '', type: '', stage: 0, eggGroup: '', sort: 'dex' }

export function useHandbook(api: ApiClient) {
  const filters = reactive<HandbookFilters>({ ...DEFAULTS })
  const data = shallowRef<Handbook | null>(null)
  const loading = ref(false)
  const error = ref('')
  let generation = 0
  let controller: AbortController | undefined
  let timer: ReturnType<typeof setTimeout> | undefined
  let active = true, loadedQuery = '', batch = false
  function query() {
    const params = new URLSearchParams()
    if (filters.search) params.set('search', filters.search.trim())
    if (filters.type) params.set('type', filters.type)
    if (filters.stage) params.set('stage', String(filters.stage))
    if (filters.eggGroup) params.set('egg_group', filters.eggGroup)
    if (filters.sort !== DEFAULTS.sort) params.set('sort', filters.sort)
    return params.toString()
  }

  function invalidate() {
    ++generation
    controller?.abort()
    clearTimeout(timer)
  }
  async function load() {
    if (!active) return
    invalidate()
    const current = generation
    controller = new AbortController()
    loading.value = true
    error.value = ''
    const key = query()
    try {
      const response = await api(`/api/handbook?${key}`, controller.signal)
      if (current === generation) { data.value = parseHandbook(response); loadedQuery = key }
    } catch (err) {
      if (current === generation) error.value = err instanceof Error ? err.message : String(err)
    } finally {
      if (current === generation) loading.value = false
    }
  }
  watch(() => ({ ...filters }), (next, previous) => {
    // 清除筛选时由 clear() 统一重拉，避免逐字段赋值拆成多次请求、首个请求还带着旧条件。
    if (batch) return
    // 输入时立即作废旧请求，不能等 debounce 结束才失效。
    invalidate()
    if (!active) return
    loading.value = true
    error.value = ''
    if (next.search !== previous.search) timer = setTimeout(load, 220)
    else void load()
  }, { flush: 'sync' })
  onScopeDispose(invalidate)
  function pause() { active = false; invalidate(); loading.value = false }
  async function resume() {
    active = true
    if (!data.value || error.value || loadedQuery !== query()) await load()
  }
  // 切号：丢掉上一个账号期间发出的请求与已加载视图，交由外壳重新 load。
  function resetAccount() {
    invalidate()
    data.value = null
    error.value = ''
    loading.value = false
    loadedQuery = ''
  }
  function clear() {
    batch = true
    Object.assign(filters, DEFAULTS)
    batch = false
    return load()
  }
  return { filters, data, loading, error, load, pause, resume, resetAccount, clear }
}
