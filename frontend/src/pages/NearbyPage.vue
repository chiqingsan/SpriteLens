<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch, type ComponentPublicInstance } from 'vue'
import { useVirtualizer } from '@tanstack/vue-virtual'
import UiIcon from '../components/UiIcon.vue'
import MedalIcon from '../components/MedalIcon.vue'
import SceneRadar from '../components/SceneRadar.vue'
import { useNearby, type NearbyHost } from '../composables/useNearby'
import type { NearbyMark } from '../types/nearby'

const props = defineProps<{ host: NearbyHost }>()
const { data, summary, loading, error, stale, load, update, pause, resume } = useNearby(props.host)
const initialLoading = computed(() => loading.value && !data.value && !error.value)
const selected = ref(''), floatingError = ref('')
const refreshing = ref(false)
async function refresh() {
  if (refreshing.value) return
  refreshing.value = true
  try { await load() } finally { refreshing.value = false }
}
watch(data, snapshot => { if (!snapshot?.actors.some(actor => actor.actor_id === selected.value)) selected.value = '' })
async function openFloating() {
  floatingError.value = ''
  try { await props.host.openFloating?.() } catch (cause) { floatingError.value = cause instanceof Error ? cause.message : String(cause) }
}
async function selectActor(id: string) {
  search.value = ''; selected.value = id; await nextTick()
  const index = rows.value.findIndex(row => row.actor_id === id)
  if (index >= 0) rowVirtualizer.value.scrollToIndex(index, { align: 'auto' })
  await nextTick()
  document.getElementById(`nearby-actor-${id}`)?.scrollIntoView({ block: 'nearest', behavior: 'auto' })
}
const search = ref(''), sort = ref('recent'), failedImages = ref(new Set<string>())
const recentOrder = ref<string[]>([])
let recentObservation: number | null = null
watch(data, snapshot => {
  if (!snapshot) {
    recentOrder.value = []
    recentObservation = null
    return
  }
  const actors = snapshot.actors
  if (snapshot.observation_id !== recentObservation) {
    recentObservation = snapshot.observation_id
    recentOrder.value = [...actors]
      .sort((a, b) => b.updated_at - a.updated_at || a.actor_id.localeCompare(b.actor_id))
      .map(actor => actor.actor_id)
    return
  }
  const currentIds = new Set(actors.map(actor => actor.actor_id))
  const knownIds = new Set(recentOrder.value)
  recentOrder.value = [
    ...recentOrder.value.filter(id => currentIds.has(id)),
    ...actors.filter(actor => !knownIds.has(actor.actor_id)).map(actor => actor.actor_id),
  ]
})
const medalMarkNames = new Set(['大块头', '小不点', '婉转声', '粗嗓门'])
function isMedalMark(mark: NearbyMark) { return medalMarkNames.has(mark.name) }
const rows = computed(() => {
  const needle = search.value.trim().toLocaleLowerCase()
  const filtered = (data.value?.actors || []).filter(row => `${row.name} ${row.config_id ?? ''} ${row.actor_id}`.toLocaleLowerCase().includes(needle))
  if (sort.value === 'name') return filtered.sort((a, b) => a.name.localeCompare(b.name, 'zh-CN') || a.actor_id.localeCompare(b.actor_id))
  const order = new Map(recentOrder.value.map((id, index) => [id, index]))
  return filtered.sort((a, b) => (order.get(a.actor_id) ?? Number.MAX_SAFE_INTEGER) - (order.get(b.actor_id) ?? Number.MAX_SAFE_INTEGER))
})
const listViewport = ref<HTMLElement | null>(null)
const rowVirtualizerOptions = computed(() => ({
  count: rows.value.length,
  getScrollElement: () => listViewport.value,
  estimateSize: () => 220,
  getItemKey: (index: number) => rows.value[index]?.actor_id ?? index,
  gap: 16,
  initialRect: { width: 640, height: 680 },
  overscan: 3,
}))
const rowVirtualizer = useVirtualizer(rowVirtualizerOptions)
const virtualRows = computed(() => rowVirtualizer.value.getVirtualItems())
const virtualCards = computed(() => virtualRows.value.flatMap(item => {
  const actor = rows.value[item.index]
  return actor ? [{ item, actor }] : []
}))
const virtualHeight = computed(() => rowVirtualizer.value.getTotalSize())
watch(rows, (next, previous) => {
  const viewport = listViewport.value
  if (!viewport || viewport.scrollTop === 0 || next.length === 0
    || next.length === previous.length && next.every((actor, index) => actor.actor_id === previous[index]?.actor_id)) return
  const top = viewport.getBoundingClientRect().top + viewport.clientTop
  const cards = [...viewport.querySelectorAll<HTMLElement>('.nearby-card')]
  const visible = cards.findIndex(card => card.getBoundingClientRect().bottom > top)
  if (visible < 0) return
  const anchor = cards[visible]!
  const currentIds = new Set(next.map(actor => `nearby-actor-${actor.actor_id}`))
  const surviving = cards.slice(visible).find(card => currentIds.has(card.id))
    ?? cards.slice(0, visible).reverse().find(card => currentIds.has(card.id))
  if (!surviving) return
  const index = next.findIndex(actor => `nearby-actor-${actor.actor_id}` === surviving.id)
  const offset = anchor.getBoundingClientRect().top - top - parseFloat(getComputedStyle(viewport).paddingTop)
  // 在 Vue 提交 DOM 前补偿锚点上方的增删，只更新滚动偏移，保留测量缓存。
  const target = rowVirtualizer.value.getOffsetForIndex(index, 'start')
  if (target) rowVirtualizer.value.scrollToOffset(Math.max(0, target[0] - offset))
})
watch([search, sort, () => summary.value?.uid, () => summary.value?.observation_id], () => {
  if (listViewport.value) listViewport.value.scrollTop = 0
}, { flush: 'post' })
const messages: Record<string, [string, string]> = {
  awaiting_identity: ['等待识别当前角色', '开始采集后重新进入游戏，确认本次角色与场景。'],
  awaiting_scene: ['等待场景精灵', '在游戏中移动或进入场景后，服务器会陆续下发附近实体。'],
  resumed_stale: ['等待当前场景数据', '收到游戏新下发的实体后显示，不展示上次缓存。'],
  battle_unverified: ['战斗中，已清空附近观察', '战斗结束后等待新的场景数据，不恢复战斗前的缓存。'],
  disconnected: ['游戏连接已断开', '重新连接游戏后会重新识别角色与场景。'],
  stopped: ['采集已停止', '开始采集并进入游戏后，这里会展示附近精灵。'],
  historical_account: ['当前为历史账号', '附近精灵只展示本次连接的观察，不读取历史附近缓存。'],
  observing: ['正在观察当前场景', '只展示服务器已下发的精灵，未观察到不代表附近没有。'],
}
const status = computed(() => messages[summary.value?.phase || 'awaiting_identity']!)
function time(value: number | null) { return value === null ? '尚无更新' : new Date(value * 1000).toLocaleTimeString('zh-CN', { hour12: false }) }
function metric(value: number | null, divisor: number, unit: string) { return value === null ? '未知' : `${(value / divisor).toLocaleString('zh-CN', { maximumFractionDigits: 3 })} ${unit}` }
function imageFailed(id: string) { failedImages.value = new Set(failedImages.value).add(id) }
function measureRow(element: Element | ComponentPublicInstance | null) {
  if (element instanceof HTMLElement) rowVirtualizer.value.measureElement(element)
}
onUnmounted(pause)
defineExpose({ update, load, pause, resume })
</script>

<template>
  <div class="nearby-page">
    <header class="nearby-heading"><div><span class="nearby-eyebrow">{{ summary?.phase === 'resumed_stale' ? '已恢复基线 · 待确认' : '当前场景 · 实时观察' }}</span><h2>附近精灵</h2><p>从游戏连接中观察附近的精灵与个体数据。</p></div><div class="nearby-heading-actions"><span class="nearby-partial">不完整观察</span><button class="ghost-button small nearby-refresh" @click="openFloating"><UiIcon name="eye" />悬浮雷达</button></div></header>
    <section class="nearby-status" aria-label="场景观察状态"><UiIcon name="eye" /><div><strong>{{ status[0] }}</strong><p>{{ status[1] }}</p></div><div class="nearby-scene"><span>场景 {{ data?.scene_id ?? '未知' }}</span><span>更新 {{ time(data?.updated_at ?? null) }}</span></div></section>
    <div class="nearby-toolbar"><label class="nearby-search"><UiIcon name="search" /><input v-model="search" type="search" aria-label="搜索附近精灵" placeholder="搜索名称、配置或实体编号"></label><label class="nearby-sort">排序<select v-model="sort" aria-label="附近精灵排序"><option value="recent">最近观察</option><option value="name">精灵名称</option></select></label><button class="ghost-button small nearby-refresh" :aria-busy="refreshing" :aria-disabled="refreshing" @click="refresh"><UiIcon name="refresh" />刷新</button></div>
    <p v-if="floatingError" class="nearby-error" role="alert">{{ floatingError }}</p>
    <p v-if="error && !stale" class="nearby-error" role="alert">{{ error }}。当前无可用数据，请刷新重试。</p>
    <p v-if="data && !data.mapping_available" class="nearby-warning" role="status">精灵映射表不可用，名称、头像及体型参考标识可能缺失；原始观察数据仍会保留。</p>
    <p v-if="data && (data.unresolved_updates || data.rejected_actors)" class="nearby-warning" role="status">有 {{ data.unresolved_updates }} 项更新尚未解析，{{ data.rejected_actors }} 项实体未能接纳；列表可能有缺失。</p>
    <div class="nearby-count"><strong>{{ rows.length }} 只<span v-if="search.trim()"> / 已观察 {{ data?.actors.length ?? 0 }} 只</span></strong><span class="nearby-count-note" :class="{ 'is-stale': stale }" :title="stale ? `刷新失败，显示的是稍早的结果${error ? '：' + error : ''}` : undefined" role="status">{{ stale ? '刷新失败，显示的是稍早的结果' : '距离与方向待校准' }}</span></div>
    <div class="nearby-workspace"><div ref="listViewport" class="nearby-list-pane">
    <section v-if="rows.length" class="nearby-grid" aria-label="附近精灵列表" :aria-busy="loading">
      <div class="nearby-virtual-space" :style="{ height: `${virtualHeight}px` }">
        <article v-for="entry in virtualCards" :key="`${data?.observation_id}:${entry.actor.actor_id}`" :ref="measureRow" class="nearby-card nearby-virtual-row" :class="{ 'is-selected': selected === entry.actor.actor_id }" :data-index="entry.item.index" :id="`nearby-actor-${entry.actor.actor_id}`" tabindex="0" role="button" :aria-pressed="selected === entry.actor.actor_id" :style="{ transform: `translateY(${entry.item.start}px)` }" @click="selected = entry.actor.actor_id" @keydown.enter="selected = entry.actor.actor_id" @keydown.space.prevent="selected = entry.actor.actor_id">
          <div class="nearby-portrait"><img v-if="entry.actor.icon_url && !failedImages.has(entry.actor.icon_url)" :src="entry.actor.icon_url" alt="" loading="lazy" @error="imageFailed(entry.actor.icon_url)"><UiIcon v-else name="eye" /></div>
          <div class="nearby-card-copy"><div class="nearby-card-title"><h3 :title="entry.actor.name">{{ entry.actor.name }}</h3><span>Lv.{{ entry.actor.level ?? '未知' }}</span></div><div class="nearby-types"><span v-for="type in entry.actor.type_names" :key="type">{{ type }}</span><span v-if="!entry.actor.type_names.length">属性未知</span></div>
            <div class="nearby-card-marks" :class="{ 'is-empty': !entry.actor.marks.length && entry.actor.attention !== 'double' }" aria-label="重点标识"><template v-for="mark in entry.actor.marks" :key="mark.name"><MedalIcon v-if="isMedalMark(mark)" :name="mark.name" :source="mark.source" /><span v-else class="nearby-reference-mark" :title="`${mark.name} · 数值参考`">{{ mark.name }}</span></template><span v-if="entry.actor.attention === 'double'" class="nearby-double-mark" title="体型与声音均命中当前参考线，尚未确认游戏奖牌">双牌</span></div>
            <dl class="nearby-metrics"><div><dt>身高</dt><dd>{{ metric(entry.actor.height, 100, 'm') }}</dd></div><div><dt>体重</dt><dd>{{ metric(entry.actor.weight, 1000, 'kg') }}</dd></div><div><dt>音量原值</dt><dd>{{ entry.actor.voice ?? '未知' }}</dd></div></dl>
            <footer><span>实体 {{ entry.actor.actor_id }}</span><time>{{ time(entry.actor.updated_at) }}</time></footer>
          </div>
        </article>
      </div>
    </section>
    <section v-else class="nearby-empty" aria-live="polite"><UiIcon :name="initialLoading ? 'refresh' : 'eye'" /><h3>{{ initialLoading ? '正在读取附近观察' : search.trim() ? '没有匹配的精灵' : '尚未观察到附近精灵' }}</h3><p>{{ search.trim() ? '试试其他名称或编号。' : status[1] }}</p></section>
    </div><div class="nearby-radar-pane"><SceneRadar :data="data" :selected="selected" :radius="data?.radar_radius_raw" @select="selectActor" /></div></div>
    <p class="nearby-footnote">仅代表本次连接已观察到的范围，不保证覆盖整个场景。实体与位置会随切号、切场景及停止采集清空。</p>
  </div>
</template>

<style scoped>
.nearby-heading-actions { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-3); }
.nearby-workspace { display: grid; grid-template-columns: minmax(260px, .85fr) minmax(0, 1.15fr); gap: var(--space-5); align-items: start; }
.nearby-list-pane { min-width: 0; height: clamp(240px, calc(100vh - 280px), 680px); overflow-y: auto; padding: 2px; }
.nearby-radar-pane { min-width: 0; position: sticky; top: var(--space-4); }
.nearby-card { cursor: pointer; }
.nearby-card.is-selected, .nearby-card:focus-visible { outline: 2px solid var(--focus-ring); outline-offset: -2px; }
@media(max-width:900px) { .nearby-workspace { grid-template-columns: minmax(0,1fr); } .nearby-radar-pane { grid-row: 1; position: static; } }
.nearby-page { min-width: 0; color: var(--ink); }
.nearby-heading, .nearby-status, .nearby-toolbar, .nearby-card-title, .nearby-count, .nearby-card footer { display: flex; align-items: center; justify-content: space-between; gap: var(--space-4); flex-wrap: wrap; }
.nearby-heading { margin-bottom: var(--space-6); align-items: flex-start; }
.nearby-heading h2 { margin: var(--space-2) 0; font-size: var(--fs-xl); }
.nearby-heading p, .nearby-status p { margin: var(--space-2) 0 0; line-height: 1.6; color: var(--muted); }
.nearby-eyebrow, .nearby-partial, .nearby-count, .nearby-footnote { font-size: var(--fs-xs); }
.nearby-eyebrow { color: var(--teal-dark); }
.nearby-partial { background: var(--amber-soft); color: var(--amber-ink); border: 1px solid var(--amber-line); padding: var(--space-2) var(--space-4); border-radius: var(--radius-sm); }
.nearby-status { padding: var(--space-5); background: var(--teal-soft); border: 1px solid var(--line); border-radius: var(--radius-sm); margin-bottom: var(--space-5); }
.nearby-status > .ui-icon { flex: none; color: var(--teal-dark); }
.nearby-status > div:first-of-type { flex: 1 1 240px; min-width: 0; }
.nearby-scene { display: grid; gap: var(--space-2); min-width: 0; color: var(--muted); font-size: var(--fs-xs); }
.nearby-scene span { min-width: 0; overflow-wrap: anywhere; }
.nearby-toolbar { min-width: 0; margin-bottom: var(--space-5); justify-content: flex-start; }
.nearby-search { display: flex; align-items: center; gap: var(--space-3); flex: 1 1 240px; min-width: 0; border: 1px solid var(--line); border-radius: var(--radius-sm); background: var(--panel); padding-inline: var(--space-4); }
.nearby-search input { width: 100%; min-width: 0; border: 0; background: none; height: 36px; color: var(--ink); }
.nearby-search:focus-within { outline: 2px solid var(--focus-ring); outline-offset: 2px; }
.nearby-sort { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-3); font-size: var(--fs-xs); min-width: 0; max-width: 100%; }
.nearby-sort select { min-width: 0; max-width: 100%; min-height: 36px; background: var(--panel); color: var(--ink); border: 1px solid var(--line); border-radius: var(--radius-sm); padding-inline: var(--space-3); }
.nearby-refresh { background: var(--panel); border: 1px solid var(--teal); color: var(--teal-dark); min-height: 36px; min-width: 0; max-width: 100%; flex-wrap: wrap; white-space: normal; }
.nearby-count { margin-bottom: var(--space-4); color: var(--muted); }
.nearby-count strong { color: var(--ink); }
.nearby-count strong span { font-weight: normal; color: var(--muted); }
.nearby-count-note { flex: 1 1 0; min-width: 0; text-align: right; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
/* 状态文案固定单行：失败提示出现/消失不改变计数行高度，避免内容区跳动；超窄视口截断，完整文案见 title。 */
.nearby-count-note.is-stale { max-width: 100%; padding: 0 var(--space-2); border-radius: var(--radius-sm); background: var(--amber-soft); color: var(--amber-ink); }
.nearby-grid { min-width: 0; container-type: inline-size; }
.nearby-virtual-space { position: relative; min-width: 0; }
.nearby-virtual-row { position: absolute; inset: 0 0 auto; }
.nearby-card { display: flex; gap: var(--space-4); min-width: 0; padding: var(--space-5); background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius-sm); }
.nearby-portrait { display: grid; place-items: center; flex: none; width: 64px; height: 64px; background: var(--surface-2); border-radius: var(--radius-sm); color: var(--muted); }
.nearby-portrait img { width: 100%; height: 100%; object-fit: contain; }
.nearby-card-copy { flex: 1; min-width: 0; }
.nearby-card-title { align-items: flex-start; flex-wrap: nowrap; gap: var(--space-2); }
.nearby-card h3 { min-width: 0; margin: 0; overflow: hidden; font-size: var(--fs-md); flex: 1 1 100px; text-overflow: ellipsis; white-space: nowrap; }
.nearby-card-title > span { color: var(--muted); font-size: var(--fs-xs); }
.nearby-types { display: flex; flex-wrap: wrap; gap: var(--space-2); margin-top: var(--space-2); }
.nearby-types span { background: var(--surface-2); color: var(--muted); border-radius: var(--radius-sm); padding: 2px var(--space-2); font-size: var(--fs-xs); }
.nearby-metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 74px), 1fr)); gap: var(--space-3); margin: var(--space-4) 0; }
.nearby-metrics dt { font-size: var(--fs-xs); color: var(--muted); }
.nearby-metrics dd { margin: var(--space-1) 0 0; font-size: var(--fs-sm); }
.nearby-card footer { border-top: 1px solid var(--line-soft); padding-top: var(--space-3); font-size: var(--fs-xs); color: var(--muted); }
.nearby-card-marks { display: flex; align-items: center; flex-wrap: nowrap; gap: var(--space-2); width: 100%; min-width: 0; height: 40px; overflow-x: auto; }
.nearby-card-marks > * { flex-shrink: 0; }
.nearby-card-marks.is-empty { visibility: hidden; }
.nearby-card-marks .medal-icon { width: 24px; height: 24px; }
.nearby-reference-mark, .nearby-double-mark { display: inline-flex; align-items: center; min-height: 24px; padding: 0 var(--space-2); border: 1px solid var(--amber-line); border-radius: var(--radius-sm); background: var(--amber-soft); color: var(--amber-ink); font-size: var(--fs-2xs); font-weight: 700; white-space: nowrap; }
.nearby-double-mark { border-color: var(--teal); background: var(--accent); color: var(--teal-deep); }
.nearby-card time { min-width: 0; overflow-wrap: anywhere; }
.nearby-empty { padding: var(--space-7) var(--space-5); min-height: 200px; display: grid; place-content: center; justify-items: center; text-align: center; border: 1px dashed var(--line); border-radius: var(--radius-sm); background: var(--panel); }
.nearby-empty h3 { font-size: var(--fs-md); margin-bottom: 0; }
.nearby-empty p, .nearby-footnote { color: var(--muted); line-height: 1.6; }
.nearby-error, .nearby-warning { padding: var(--space-4); border-radius: var(--radius-sm); line-height: 1.6; }
.nearby-error { background: var(--danger-soft); color: var(--danger-ink); }
.nearby-warning { background: var(--amber-soft); color: var(--amber-ink); }
.nearby-page :is(p, h3, span, dd, strong) { overflow-wrap: anywhere; }
@media(max-width:480px) { .nearby-card { flex-direction: column; } .nearby-portrait { width: 48px; height: 48px; } }
@container(max-width:300px) { .nearby-card { flex-direction: column; } }
@media(max-width:900px) { .nearby-status { align-items: flex-start; } .nearby-scene { flex: 1 1 100%; grid-template-columns: repeat(2, minmax(0, 1fr)); } .nearby-search { flex-basis: 100%; } }
</style>
