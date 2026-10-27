<script setup lang="ts">
import { computed, onUnmounted, ref, shallowRef } from 'vue'
import SceneRadar from '../components/SceneRadar.vue'
import MedalIcon from '../components/MedalIcon.vue'
import UiIcon from '../components/UiIcon.vue'
import { useWorldMaps } from '../composables/useWorldMaps'
import { usableWorldMap } from '../types/worldMap'
import { nearbyAttentionTone, parseNearby, parseNearbySummary, type NearbyActor, type NearbySnapshot, type NearbySummary } from '../types/nearby'
const props = defineProps<{ channel: BroadcastChannel; host: { close: () => Promise<unknown>; setOpacity: (percent: number) => Promise<unknown>; loadMaps?: () => Promise<unknown> } }>()
const data = shallowRef<NearbySnapshot | null>(null), summary = shallowRef<NearbySummary | null>(null)
const { catalog, error: mapsError, refresh: refreshMaps, stop: stopMaps } = useWorldMaps(props.host.loadMaps)
const currentMap = computed(() => usableWorldMap(catalog.value, data.value?.resource_id ?? null))
void refreshMaps()
onUnmounted(stopMaps)
const error = ref(''), stale = ref(false), staleMessage = ref(''), selected = ref(''), opacity = ref(85), settingsOpen = ref(false), linkLost = ref(false)
const displayError = computed(() => error.value || mapsError.value)
let pendingOpacity: number | null = null, applying = false, confirmedOpacity = 85
const HEARTBEAT_TIMEOUT = 3000
let lastMessageAt = Date.now()
function clearStale() { stale.value = false; staleMessage.value = '' }
function markMessage() {
  lastMessageAt = Date.now()
  if (!linkLost.value) return
  linkLost.value = false; error.value = ''
  // 失效期间可能错过快照，恢复时重新订阅让主窗口补发一份当前周期数据。
  props.channel.postMessage({ kind: 'subscribe' })
}
function attentionRank(actor: NearbyActor) {
  const fullSize = actor.marks.some(mark => mark.name === '满重')
  const fullVoice = actor.marks.some(mark => mark.name === '满分')
  if (actor.attention === 'double') return fullSize && fullVoice ? 0 : 1
  return fullSize || fullVoice ? 2 : 3
}
const attentionActors = computed(() => [...(data.value?.actors || [])]
  .filter(actor => actor.attention !== 'normal')
  .sort((a, b) => attentionRank(a) - attentionRank(b) || a.actor_id.localeCompare(b.actor_id)))
const failedImages = ref(new Set<string>())
async function flushOpacity() {
  if (applying || pendingOpacity === null) return
  const value = pendingOpacity; pendingOpacity = null; applying = true
  try { await props.host.setOpacity(value); confirmedOpacity = value }
  catch (cause) { opacity.value = confirmedOpacity; pendingOpacity = null; error.value = cause instanceof Error ? cause.message : String(cause) }
  finally { applying = false; if (!closed && pendingOpacity !== null) void flushOpacity() }
}
function changeOpacity(event: Event) { opacity.value = Number((event.target as HTMLInputElement).value); pendingOpacity = opacity.value; void flushOpacity() }
function imageFailed(url: string) { failedImages.value = new Set(failedImages.value).add(url) }
function selectAttention(actor: NearbyActor) { selected.value = actor.actor_id }
function scrollAttention(event: WheelEvent) {
  const target = event.currentTarget as HTMLElement
  if (target.scrollWidth <= target.clientWidth || Math.abs(event.deltaY) <= Math.abs(event.deltaX)) return
  target.scrollLeft += event.deltaY
  event.preventDefault()
}
async function close() { try { await props.host.close() } catch (cause) { error.value = cause instanceof Error ? cause.message : String(cause) } }
props.channel.onmessage = event => {
  markMessage()
  try {
    if (event.data.kind === 'summary') {
      const next = parseNearbySummary(event.data.summary)
      if (summary.value && next.uid === summary.value.uid && next.version < summary.value.version) return
      if (!summary.value || next.uid !== summary.value.uid || next.observation_id !== summary.value.observation_id) { data.value = null; selected.value = ''; clearStale() }
      summary.value = next
    } else if (event.data.kind === 'snapshot') {
      const next = parseNearby(event.data.payload), expected = summary.value
      if (expected && (next.uid !== expected.uid || next.observation_id < expected.observation_id)) return
      if (data.value && next.uid === data.value.uid && next.version < data.value.version) return
      data.value = next
      if (!expected || next.version >= expected.version) summary.value = next
      if (!next.actors.some(actor => actor.actor_id === selected.value)) selected.value = ''
      error.value = ''; clearStale()
    } else if (event.data.kind === 'stale') {
      /* 刷新失败但主窗口仍有同周期图像：保留实体，只标注可能过期，等待下一次成功快照清除。 */
      staleMessage.value = `刷新失败，显示的是稍早的结果${event.data.message ? '：' + event.data.message : ''}`
      stale.value = true
    } else if (event.data.kind === 'error') { data.value = null; selected.value = ''; error.value = String(event.data.message); clearStale() }
  } catch (cause) { data.value = null; selected.value = ''; error.value = cause instanceof Error ? cause.message : String(cause); clearStale() }
}
props.channel.postMessage({ kind: 'subscribe' })
let closed = false
function checkHeartbeat() {
  if (closed || linkLost.value || Date.now() - lastMessageAt <= HEARTBEAT_TIMEOUT) return
  // 主窗口 JS 挂死、采集连接断开或事件循环阻塞时不再有任何消息，清掉旧图并明确提示，恢复后由新消息自动清除。
  linkLost.value = true
  data.value = null; selected.value = ''; clearStale()
  error.value = '数据已失效（采集连接断开或主窗口未响应）'
}
const heartbeatTimer = window.setInterval(checkHeartbeat, 250)
function leave() {
  if (closed) return
  closed = true; pendingOpacity = null
  window.clearInterval(heartbeatTimer)
  props.channel.postMessage({ kind: 'unsubscribe' }); props.channel.close()
}
window.addEventListener('pagehide', leave, { once: true })
onUnmounted(() => { window.removeEventListener('pagehide', leave); leave() })
</script>
<template>
  <main class="floating-radar">
    <header class="floating-titlebar"><div class="floating-drag"><UiIcon name="eye"/><strong>附近雷达</strong><span v-if="summary?.uid" :title="`当前观察账号 ${summary.uid}`">账号 {{ summary.uid.slice(-6) }}</span><span>{{ data?.actors.length ?? 0 }} 只</span></div><div class="floating-legend" aria-label="雷达目标图例"><span><i class="floating-legend-dot" />普通</span><span><i class="floating-legend-dot is-marked" />单牌</span><span><i class="floating-legend-dot is-double" />双牌</span></div><button class="floating-settings" :aria-expanded="settingsOpen" aria-label="雷达设置" @click.stop="settingsOpen = !settingsOpen"><UiIcon name="settings"/></button><button class="floating-close" aria-label="关闭悬浮雷达" @click="close"><UiIcon name="x"/></button></header>
    <div v-if="settingsOpen" class="floating-settings-panel" role="dialog" aria-label="雷达设置"><label for="radar-opacity">不透明度 <output for="radar-opacity">{{ opacity }}%</output></label><input id="radar-opacity" type="range" min="35" max="90" step="1" :value="opacity" @input="changeOpacity"></div>
    <div class="floating-content"><p v-if="displayError || stale" class="floating-error" :class="{ 'is-stale': stale && !displayError }" :role="displayError ? 'alert' : 'status'">{{ displayError || staleMessage }}</p><div class="floating-attention-slot" aria-label="有标记精灵" @wheel="scrollAttention"><div class="floating-attention-list" :class="{ 'is-empty': !attentionActors.length }"><button v-for="actor in attentionActors" :key="actor.actor_id" class="floating-attention-chip" :class="[`attention-tone-${nearbyAttentionTone(actor.actor_id)}`, { selected: selected === actor.actor_id }]" :aria-pressed="selected === actor.actor_id" :aria-label="`${actor.name}，${actor.attention === 'double' ? '双牌' : '单牌'}`" @click="selectAttention(actor)"><span class="floating-attention-avatar"><img v-if="actor.icon_url && !failedImages.has(actor.icon_url)" :src="actor.icon_url" alt="" @error="imageFailed(actor.icon_url)"><UiIcon v-else name="eye"/></span><span class="floating-attention-medals"><MedalIcon v-for="mark in actor.marks" :key="mark.name" :name="mark.name" :source="mark.source"/></span></button></div></div><SceneRadar :data="data" :map="currentMap" :selected="selected" :radius="data?.radar_radius_raw" compact @select="selected = $event" /></div>
  </main>
</template>
<style scoped>
.floating-radar { --panel: var(--radar-overlay-bg); --surface-1: transparent; --line: var(--radar-overlay-line); --line-soft: var(--radar-overlay-line); --ink: var(--radar-overlay-ink); --muted: var(--radar-overlay-muted); --teal: var(--radar-overlay-point); --teal-dark: var(--radar-overlay-point); --radar-player: #67e8f9; --accent: var(--radar-overlay-line); --focus-ring: var(--radar-overlay-point); position: fixed; inset: 0; min-width: 0; display: flex; flex-direction: column; background: var(--radar-overlay-bg); color: var(--radar-overlay-ink); }
.floating-titlebar { flex: none; display: grid; grid-template-columns: minmax(0, 1fr) auto 40px 40px; align-items: stretch; min-height: 40px; padding-left: var(--space-3); border-bottom: 1px solid var(--radar-overlay-line); -webkit-app-region: drag; }
.floating-drag { display: flex; align-items: center; min-width: 0; gap: var(--space-3); user-select: none; }
.floating-drag strong { min-width: 0; overflow: hidden; font-size: var(--fs-sm); text-overflow: ellipsis; white-space: nowrap; }
.floating-drag span { font-size: var(--fs-xs); color: var(--radar-overlay-muted); }
.floating-drag .ui-icon { width: 16px; height: 16px; color: var(--radar-overlay-point); }
.floating-legend { display: flex; align-items: center; justify-content: flex-end; gap: var(--space-2); min-width: max-content; padding: 0 var(--space-2); color: var(--radar-overlay-muted); font-size: var(--fs-2xs); white-space: nowrap; }
.floating-legend span { display: inline-flex; align-items: center; gap: var(--space-1); }
.floating-legend-dot { width: 9px; height: 9px; flex: none; border-radius: 50%; background: var(--radar-overlay-point); }
.floating-legend-dot.is-marked { background: var(--amber-bright); }
.floating-legend-dot.is-double { width: 11px; height: 11px; background: var(--danger); border: 1px solid var(--danger); }
.floating-settings, .floating-close { display: grid; place-items: center; width: 40px; background: transparent; color: var(--radar-overlay-muted); -webkit-app-region: no-drag; border-radius: 0; }
.floating-settings:hover, .floating-settings[aria-expanded="true"], .floating-close:hover { background: var(--radar-overlay-line); color: var(--radar-overlay-ink); }
.floating-settings:focus-visible, .floating-close:focus-visible { outline: 2px solid var(--radar-overlay-point); outline-offset: -3px; }
.floating-settings-panel { position: absolute; z-index: 4; top: 48px; right: 48px; display: grid; gap: var(--space-3); width: min(240px, calc(100% - 56px)); padding: var(--space-4); background: var(--radar-overlay-bg); border: 1px solid var(--radar-overlay-line); border-radius: var(--radius-sm); box-shadow: var(--shadow-pop); color: var(--radar-overlay-ink); }
.floating-settings-panel label { display: flex; justify-content: space-between; gap: var(--space-3); font-size: var(--fs-xs); }
.floating-settings-panel input { width: 100%; min-width: 0; accent-color: var(--radar-overlay-point); }
.floating-content { flex: 1; min-height: 0; display: flex; flex-direction: column; padding: var(--space-3) var(--space-4); }
.floating-error { flex: none; max-height: 25%; overflow-y: auto; font-size: var(--fs-xs); overflow-wrap: anywhere; line-height: 1.5; color: var(--radar-overlay-ink); border-left: 2px solid var(--amber); padding-left: var(--space-3); }
.floating-error.is-stale { color: var(--radar-overlay-muted); }
.floating-attention-slot { flex: none; height: 56px; min-height: 56px; overflow-x: auto; overflow-y: hidden; box-sizing: border-box; padding-bottom: var(--space-3); scrollbar-width: none; -ms-overflow-style: none; }
.floating-attention-slot::-webkit-scrollbar { display: none; }
.floating-attention-list { display: flex; flex-wrap: nowrap; align-items: flex-start; gap: var(--space-2); width: max-content; min-width: 100%; min-height: 32px; }
.floating-attention-list.is-empty { visibility: hidden; }
.floating-attention-chip { display: inline-flex; align-items: center; flex: none; gap: var(--space-2); min-width: 0; max-width: none; padding: var(--space-1) var(--space-3) var(--space-1) var(--space-1); border: 1px solid color-mix(in srgb, var(--radar-overlay-ink) 38%, transparent); border-radius: 999px; box-shadow: 0 2px 7px rgba(0, 0, 0, .24); background: var(--radar-attention-0); color: var(--radar-overlay-ink); font-size: var(--fs-2xs); white-space: nowrap; }
.floating-attention-chip.attention-tone-0 { background: var(--radar-attention-0); }
.floating-attention-chip.attention-tone-1 { background: var(--radar-attention-1); }
.floating-attention-chip.attention-tone-2 { background: var(--radar-attention-2); }
.floating-attention-chip.attention-tone-3 { background: var(--radar-attention-3); }
.floating-attention-chip.attention-tone-4 { background: var(--radar-attention-4); }
.floating-attention-chip:hover, .floating-attention-chip.selected { border-color: var(--radar-overlay-ink); }
.floating-attention-avatar { display: grid; place-items: center; width: 24px; height: 24px; flex: none; overflow: hidden; border-radius: 50%; background: var(--radar-overlay-line); }
.floating-attention-avatar img { width: 100%; height: 100%; object-fit: cover; }
.floating-attention-avatar .ui-icon { width: 14px; height: 14px; }
.floating-attention-medals { display: inline-flex; align-items: center; gap: 1px; min-width: 0; }
.floating-attention-medals :deep(.medal-icon) { width: 22px; height: 22px; object-fit: contain; }
.floating-attention-medals :deep(.medal-icon-text) { max-width: 3em; overflow: hidden; font-size: var(--fs-3xs); text-overflow: ellipsis; }
@media (max-width: 360px) { .floating-drag { gap: var(--space-2); } .floating-drag span { display: none; } .floating-legend { gap: var(--space-1); padding-inline: var(--space-1); } }
</style>
