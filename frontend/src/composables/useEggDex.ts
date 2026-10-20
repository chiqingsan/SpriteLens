import { onScopeDispose, reactive, ref, shallowRef, watch } from 'vue'
import type { ApiClient } from '../api/client'
import { parseEggDex, type EggDex } from '../types/eggDex'

export function useEggDex(api: ApiClient) {
  const filters = reactive({ search: '', group: '', egg_type: '', hatch_min_hours: '' })
  const data = shallowRef<EggDex | null>(null)
  const loading = ref(false)
  const error = ref('')
  let generation = 0
  let controller: AbortController | undefined
  let timer: ReturnType<typeof setTimeout> | undefined
  let active = true, loadedQuery = '', batch = false
  function query() {
    const params = new URLSearchParams()
    Object.entries(filters).forEach(([key, value]) => { if (value) params.set(key, value.trim()) })
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
      const response = await api(`/api/eggs?${key}`, controller.signal)
      if (current === generation) { data.value = parseEggDex(response); loadedQuery = key }
    } catch (err) {
      if (current === generation) error.value = err instanceof Error ? err.message : String(err)
    } finally {
      if (current === generation) loading.value = false
    }
  }
  watch(() => ({ ...filters }), (next, previous) => {
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
  function clear() {
    batch = true
    Object.assign(filters, { search: '', group: '', egg_type: '', hatch_min_hours: '' })
    batch = false
    return load()
  }
  return { filters, data, loading, error, load, pause, resume, clear }
}
