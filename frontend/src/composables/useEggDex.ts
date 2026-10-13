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

  function invalidate() {
    ++generation
    controller?.abort()
    clearTimeout(timer)
  }
  async function load() {
    invalidate()
    const current = generation
    controller = new AbortController()
    loading.value = true
    error.value = ''
    const params = new URLSearchParams()
    Object.entries(filters).forEach(([key, value]) => { if (value) params.set(key, value.trim()) })
    try {
      const payload = parseEggDex(await api(`/api/eggs?${params}`, controller.signal))
      if (current === generation) data.value = payload
    } catch (err) {
      if (current === generation) error.value = err instanceof Error ? err.message : String(err)
    } finally {
      if (current === generation) loading.value = false
    }
  }
  watch(() => ({ ...filters }), (next, previous) => {
    // 输入时立即作废旧请求，不能等 debounce 结束才失效。
    invalidate()
    loading.value = true
    error.value = ''
    if (next.search !== previous.search) timer = setTimeout(load, 220)
    else void load()
  }, { flush: 'sync' })
  onScopeDispose(invalidate)
  function clear() { Object.assign(filters, { search: '', group: '', egg_type: '', hatch_min_hours: '' }) }
  return { filters, data, loading, error, load, clear }
}
