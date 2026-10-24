import { ref, shallowRef } from 'vue'
import { parseNearby, parseNearbySummary, type NearbySummary, type NearbySnapshot } from '../types/nearby'

export interface NearbyHost { load: (signal: AbortSignal) => Promise<unknown>; openFloating?: () => Promise<unknown> }
export function useNearby(host: NearbyHost) {
  const data = shallowRef<NearbySnapshot | null>(null), summary = shallowRef<NearbySummary | null>(null)
  const loading = ref(false), error = ref(''), stale = ref(false)
  let active = true, generation = 0, controller: AbortController | null = null, refreshQueued = false
  async function load() {
    if (!active) return
    controller?.abort()
    const current = ++generation
    controller = new AbortController()
    const requested = summary.value
    refreshQueued = false
    loading.value = true
    if (!data.value) error.value = ''
    try {
      const next = parseNearby(await host.load(controller.signal))
      if (!active || current !== generation) return
      const expected = summary.value
      if (expected && (next.uid !== expected.uid || next.observation_id < expected.observation_id)) return
      if (requested && next.uid === requested.uid && next.version < requested.version) return
      if (data.value && next.uid === data.value.uid && next.version < data.value.version) return
      data.value = next
      // 同周期推送可能已领先于慢请求；先提交有效进展，再合并追赶，不能永远等待追平。
      if (!expected || next.version >= expected.version) summary.value = next
      error.value = ''; stale.value = false
    } catch (cause) {
      if (active && current === generation) {
        const message = cause instanceof Error ? cause.message : String(cause)
        const latest = summary.value, currentData = data.value
        const sameCycle = Boolean(currentData && latest && currentData.uid === latest.uid && currentData.observation_id === latest.observation_id)
        // 同一观察周期内的刷新失败保留上次结果，仅标记为过期；否则清空，避免展示失效数据。
        data.value = sameCycle ? currentData : null
        stale.value = sameCycle
        error.value = message
      }
    } finally {
      if (active && current === generation) {
        loading.value = false
        const latest = summary.value, currentData = data.value
        const needsRefresh = Boolean(latest && (!currentData || latest.uid !== currentData.uid || latest.observation_id !== currentData.observation_id || latest.version > currentData.version))
        if (refreshQueued && needsRefresh) {
          refreshQueued = false
          void load()
        } else refreshQueued = false
      }
    }
  }
  function update(value: unknown) {
    if (value === null || value === undefined) {
      controller?.abort(); controller = null; ++generation
      data.value = null; summary.value = null; loading.value = false; error.value = ''; stale.value = false
      return
    }
    let next: NearbySummary
    try { next = parseNearbySummary(value) }
    catch (cause) {
      controller?.abort(); controller = null; ++generation
      data.value = null; summary.value = null; loading.value = false; stale.value = false
      error.value = cause instanceof Error ? cause.message : String(cause)
      return
    }
    const previous = summary.value
    if (previous && next.uid === previous.uid && next.version < previous.version) return
    const changed = !previous || next.uid !== previous.uid || next.observation_id !== previous.observation_id
    summary.value = next
    if (changed) {
      controller?.abort(); ++generation; loading.value = false; refreshQueued = false
      data.value = null; error.value = ''; stale.value = false
    }
    if (!active) return
    if (!data.value || changed || next.version > data.value.version) {
      if (loading.value) refreshQueued = true
      else void load()
    }
  }
  function pause() { active = false; refreshQueued = false; ++generation; controller?.abort(); loading.value = false }
  function resume() { active = true }
  return { data, summary, loading, error, stale, load, update, pause, resume }
}
