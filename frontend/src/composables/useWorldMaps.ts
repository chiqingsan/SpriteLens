import { ref, shallowRef } from 'vue'
import { parseWorldMaps, type WorldMapCatalog } from '../types/worldMap'

/** 清单读取超时：与附近页快照读取保持一致，避免地图按钮一直停在“正在读取”。 */
const LOAD_TIMEOUT_MS = 8000

/** 地图清单按会话缓存：只在进入附近页时读一次，失败后由用户点“重试”显式重载。 */
export function useWorldMaps(load: (() => Promise<unknown>) | undefined) {
  const catalog = shallowRef<WorldMapCatalog | null>(null)
  const loading = ref(false), error = ref('')
  let active = true, generation = 0
  async function refresh() {
    if (!load || !active) return
    const current = ++generation
    loading.value = true
    let timer: ReturnType<typeof setTimeout> | undefined
    try {
      const timeout = new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new Error('地图清单请求超时，请重试')), LOAD_TIMEOUT_MS)
      })
      const next = parseWorldMaps(await Promise.race([load(), timeout]))
      if (!active || current !== generation) return
      catalog.value = next
      error.value = ''
    } catch (cause) {
      if (!active || current !== generation) return
      error.value = cause instanceof Error ? cause.message : String(cause)
      // 清单损坏时整块失效：不能拿半份地图画点，已加载的旧清单也不再可信。
      catalog.value = null
    } finally {
      clearTimeout(timer)
      if (active && current === generation) loading.value = false
    }
  }
  function stop() { active = false; ++generation }
  return { catalog, loading, error, refresh, stop }
}
