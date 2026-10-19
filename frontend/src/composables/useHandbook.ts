import { onScopeDispose, reactive, ref, shallowRef, watch } from 'vue'
import type { ApiClient } from '../api/client'
import { parseHandbook, type Handbook } from '../types/handbook'

export type HandbookMode = 'all' | 'collected' | 'uncollected'

export function useHandbook(api: ApiClient) {
  const filters = reactive<{ search: string; type: string; mode: HandbookMode }>(
    { search: '', type: '', mode: 'all' })
  const data = shallowRef<Handbook | null>(null)
  const loading = ref(false)
  const error = ref('')
  let generation = 0
  let controller: AbortController | undefined
  let timer: ReturnType<typeof setTimeout> | undefined
  let active = true, loadedQuery = ''
  function query() {
    const params = new URLSearchParams()
    if (filters.search) params.set('search', filters.search.trim())
    if (filters.type) params.set('type', filters.type)
    if (filters.mode === 'collected') params.set('collected', '1')
    if (filters.mode === 'uncollected') params.set('uncollected', '1')
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
  // 切号：旧账号的收集状态不能留在页面上，清空后由外壳重新 load。
  function resetAccount() {
    invalidate()
    data.value = null
    error.value = ''
    loading.value = false
    loadedQuery = ''
  }
  function clear() { Object.assign(filters, { search: '', type: '', mode: 'all' as HandbookMode }) }
  return { filters, data, loading, error, load, pause, resume, resetAccount, clear }
}
