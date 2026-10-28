import { ref, shallowRef } from 'vue'
import { parseNearby, parseNearbySummary, type NearbySummary, type NearbySnapshot } from '../types/nearby'

/** 后台自动同步的最小间隔：短时间内多次版本推进合并成一次读取，避免按钮与骨架跟着每条推送闪动。 */
export const AUTO_LOAD_INTERVAL_MS = 500

export interface NearbyAlertHost {
  enabled(): boolean
  toggle(next?: boolean): boolean
}

export interface NearbyHost {
  load: (signal: AbortSignal) => Promise<unknown>
  loadMaps?: () => Promise<unknown>
  openFloating?: () => Promise<unknown>
  /** 清空当前地图的本次足迹；旧壳层没有该能力时页面不渲染清除按钮。 */
  resetCoverage?: (owner: { uid: string; resource_id: string; observation_id: number }) => Promise<unknown>
  alert?: NearbyAlertHost
}

export function useNearby(host: NearbyHost) {
  const data = shallowRef<NearbySnapshot | null>(null)
  const summary = shallowRef<NearbySummary | null>(null)
  // loading 只表达用户可感知的加载：首次读取（还没有 data）与手动刷新。
  // 版本推进触发的后台同步不进 loading，否则刷新按钮、骨架与 aria-busy 会随每条推送反复变化。
  const loading = ref(false)
  const error = ref('')
  const stale = ref(false)
  let active = true
  let generation = 0
  let controller: AbortController | null = null
  let inflight = false
  let pending = false
  let autoTimer: ReturnType<typeof setTimeout> | null = null
  let lastAutoAt = 0

  function clearAutoTimer() {
    if (autoTimer !== null) { clearTimeout(autoTimer); autoTimer = null }
  }

  /** 摘要是否已经领先于已提交的数据；只有真的需要新内容时才发请求。 */
  function needsFresh() {
    const latest = summary.value
    if (!latest) return false
    const current = data.value
    return !current || latest.uid !== current.uid
      || latest.observation_id !== current.observation_id || latest.version > current.version
  }

  /** 归属失效（切号/断开/解包失败）时清空全部状态，旧请求与旧数据都不再有效。 */
  function clearState() {
    clearAutoTimer()
    controller?.abort()
    controller = null
    ++generation
    inflight = false
    pending = false
    loading.value = false
    data.value = null
    summary.value = null
    error.value = ''
    stale.value = false
  }

  /** 真正发起一次读取；showLoading 为 true 时进入用户可感知的加载态（首次读取/手动刷新）。 */
  async function runLoad(showLoading: boolean): Promise<void> {
    if (!active) { pending = true; return }
    clearAutoTimer()
    controller?.abort()
    const current = ++generation
    const request = new AbortController()
    controller = request
    const requested = summary.value
    pending = false
    inflight = true
    if (showLoading) {
      loading.value = true
      if (!data.value) error.value = ''
    } else {
      // 后台同步只记录间隔基准：不进 loading，也不改按钮与骨架。
      lastAutoAt = Date.now()
    }
    try {
      const next = parseNearby(await host.load(request.signal))
      if (!active || current !== generation) return
      const expected = summary.value
      // 账号或观察周期不匹配、版本倒退的响应一律不接纳：旧周期晚到的结果不能覆盖新快照。
      if (expected && (next.uid !== expected.uid || next.observation_id < expected.observation_id)) return
      if (requested && next.uid === requested.uid && next.version < requested.version) return
      if (data.value && next.uid === data.value.uid && next.version < data.value.version) return
      data.value = next
      if (!expected || next.version >= expected.version) summary.value = next
      error.value = ''
      stale.value = false
    } catch (cause) {
      if (!active || current !== generation) return
      const message = cause instanceof Error ? cause.message : String(cause)
      const latest = summary.value
      const currentData = data.value
      // 同一观察周期内失败只标记过期并保留已提交内容；周期变化或切号后的失败才清空。
      const sameCycle = Boolean(currentData && latest && currentData.uid === latest.uid && currentData.observation_id === latest.observation_id)
      data.value = sameCycle ? currentData : null
      stale.value = sameCycle
      error.value = message
    } finally {
      if (current !== generation) return
      inflight = false
      if (showLoading) loading.value = false
      if (!active) { pending = false; return }
      // 读取期间到达的新版本只补一次，且不受自动节流：它承载的已经是用户可见的推送。
      const follow = pending && needsFresh()
      pending = false
      if (follow) void runLoad(false)
    }
  }

  /** 手动刷新：只有它和首次读取会进入 loading。 */
  function load(): Promise<void> { return runLoad(true) }

  /** 后台同步：领先当前快照时按 AUTO_LOAD_INTERVAL_MS 合并，leading + trailing 期间只补一次最新。 */
  function autoLoadSoon() {
    if (!active) { pending = true; return }
    if (inflight) { pending = true; return }
    if (autoTimer !== null) return
    const wait = AUTO_LOAD_INTERVAL_MS - (Date.now() - lastAutoAt)
    if (wait <= 0) { void runLoad(false); return }
    autoTimer = setTimeout(() => {
      autoTimer = null
      void runLoad(false)
    }, wait)
  }

  function update(value: unknown) {
    if (value == null) { clearState(); return }
    let next: NearbySummary
    try {
      next = parseNearbySummary(value)
    } catch (cause) {
      clearState()
      error.value = cause instanceof Error ? cause.message : String(cause)
      return
    }
    const previous = summary.value
    // 版本倒退的推送直接丢弃，不打断当前读取。
    if (previous && next.uid === previous.uid && next.version < previous.version) return
    const changed = !previous || next.uid !== previous.uid || next.observation_id !== previous.observation_id
    summary.value = next
    if (changed) {
      // 切号或换观察周期：归属与场景已经变化，旧内容立即清空，并立即读一次（不受节流）。
      clearAutoTimer()
      controller?.abort()
      controller = null
      ++generation
      inflight = false
      pending = false
      loading.value = false
      data.value = null
      error.value = ''
      stale.value = false
      if (!active) { pending = true; return }
      void runLoad(true)
      return
    }
    if (!active) { pending = needsFresh(); return }
    if (!needsFresh()) return
    autoLoadSoon()
  }

  function pause() {
    active = false
    clearAutoTimer()
    pending = needsFresh()
    ++generation
    controller?.abort()
    inflight = false
    loading.value = false
  }

  function resume() {
    if (active) return
    active = true
    if (!pending) return
    pending = false
    // 回页时把暂停期间积压的那一份补上；有数据就只做后台同步，避免骨架与按钮闪动。
    void runLoad(!data.value)
  }

  return { data, summary, loading, error, stale, load, update, pause, resume }
}
