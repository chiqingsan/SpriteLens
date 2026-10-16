import { ref, shallowRef } from 'vue'
import { parseHome, type HomeSnapshot } from '../types/home'

export interface HomeHost {
  load: () => Promise<unknown | null>
  cancel: () => void
  versionChanged: (version: number) => void
}

export function useHome(host: HomeHost) {
  const data = shallowRef<HomeSnapshot | null>(null)
  const loading = ref(false)
  const error = ref('')
  let generation = 0

  async function load() {
    const current = ++generation
    loading.value = true
    error.value = ''
    try {
      const payload = await host.load()
      if (current !== generation || payload === null) return
      const next = parseHome(payload)
      data.value = next
      host.versionChanged(next.version)
    } catch (cause) {
      if (current === generation) error.value = cause instanceof Error ? cause.message : String(cause)
    } finally {
      if (current === generation) loading.value = false
    }
  }

  async function resume(version: number) {
    if (!data.value || data.value.version < version || error.value) await load()
  }

  function pause() {
    ++generation
    host.cancel()
    loading.value = false
  }

  function resetAccount() {
    pause()
    data.value = null
    error.value = ''
  }

  return { data, loading, error, load, resume, pause, resetAccount }
}
