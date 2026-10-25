<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch, type ComponentPublicInstance } from 'vue'
import { useVirtualizer } from '@tanstack/vue-virtual'
import UiIcon from '../components/UiIcon.vue'
import MedalIcon from '../components/MedalIcon.vue'
import SceneRadar from '../components/SceneRadar.vue'
import { useNearby, type NearbyHost } from '../composables/useNearby'
import type { NearbyActor, NearbyMark } from '../types/nearby'

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
// 与悬浮雷达 attentionRank 同一口径：满重或满分且双牌的优先，同级保持最近观察顺序。
function attentionRank(actor: NearbyActor) {
  const full = actor.marks.some(mark => mark.name === '满重' || mark.name === '满分')
  if (actor.attention === 'double') return actor.marks.some(mark => mark.name === '满重') && actor.marks.some(mark => mark.name === '满分') ? 0 : 1
  return full ? 2 : actor.attention === 'marked' ? 3 : 4
}
const rows = computed(() => {
  const needle = search.value.trim().toLocaleLowerCase()
  const filtered = (data.value?.actors || []).filter(row => `${row.name} ${row.config_id ?? ''} ${row.actor_id}`.toLocaleLowerCase().includes(needle))
  const order = new Map(recentOrder.value.map((id, index) => [id, index]))
  const recent = (a: NearbyActor, b: NearbyActor) => (order.get(a.actor_id) ?? Number.MAX_SAFE_INTEGER) - (order.get(b.actor_id) ?? Number.MAX_SAFE_INTEGER)
  if (sort.value === 'marks') return filtered.sort((a, b) => attentionRank(a) - attentionRank(b) || recent(a, b))
  return filtered.sort(recent)
})
const listViewport = ref<HTMLElement | null>(null)
const rowVirtualizerOptions = computed(() => ({
  count: rows.value.length,
  getScrollElement: () => listViewport.value,
  estimateSize: () => 108,
  getItemKey: (index: number) => rows.value[index]?.actor_id ?? index,
  gap: 12,
  initialRect: { width: 640, height: 600 },
  overscan: 4,
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
// 状态文案只保留用户能直接理解的短句；完整解释放在 title 里，避免首屏堆字。
const labels: Record<string, string> = {
  awaiting_identity: '未连接游戏',
  awaiting_scene: '等待场景数据',
  resumed_stale: '恢复场景中',
  battle_unverified: '战斗中暂停',
  disconnected: '连接已断开',
  stopped: '采集已停止',
  historical_account: '历史账号',
  observing: '实时观察中',
}
const hints: Record<string, string> = {
  awaiting_identity: '开始采集后重新进入游戏，确认本次角色与场景。',
  awaiting_scene: '在游戏中移动或进入场景后，服务器会陆续下发附近实体。',
  resumed_stale: '收到游戏新下发的实体后显示，不展示上次缓存。',
  battle_unverified: '战斗判定期间清空附近观察，结束后等待新的场景数据。',
  disconnected: '重新连接游戏后会重新识别角色与场景。',
  stopped: '开始采集并进入游戏后，这里会展示附近精灵。',
  historical_account: '附近精灵只展示本次连接的观察，不读取历史附近缓存。',
  observing: '只展示服务器已下发的精灵，未观察到不代表附近没有。',
}
const phase = computed(() => summary.value?.phase || 'awaiting_identity')
const status = computed(() => labels[phase.value] ?? labels.awaiting_identity!)
const statusHint = computed(() => hints[phase.value] ?? hints.awaiting_identity!)
// 未解析更新只影响完整性，放成计数行旁的一句浅色提示，避免整条黄色横幅常驻。
const incomplete = computed(() => {
  const snapshot = data.value
  return snapshot !== null && (snapshot.unresolved_updates > 0 || snapshot.rejected_actors > 0)
})
const countNote = computed(() => {
  if (stale.value) return '刷新失败，显示的是稍早的结果'
  return incomplete.value ? '部分精灵可能未显示' : ''
})
const countNoteTitle = computed(() => {
  if (stale.value) return `刷新失败，显示的是稍早的结果${error.value ? '：' + error.value : ''}`
  const snapshot = data.value
  if (!incomplete.value || snapshot === null) return '雷达外环为原始坐标单位，尚未校准米制'
  return `有 ${snapshot.unresolved_updates} 条更新未能解析，${snapshot.rejected_actors} 个实体未能接纳；列表可能有缺失。`
})
function time(value: number | null) { return value === null ? '尚无更新' : new Date(value * 1000).toLocaleTimeString('zh-CN', { hour12: false }) }
function relativeTime(value: number | null) {
  if (value === null) return '尚无更新'
  const seconds = Math.max(0, Math.floor(Date.now() / 1000 - value))
  if (seconds < 60) return '刚刚'
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`
  return time(value)
}
function shortId(value: string) { return value.length > 10 ? `…${value.slice(-9)}` : value }
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
    <header class="nearby-heading">
      <div class="nearby-heading-main">
        <h2 class="sr-only">附近精灵</h2>
        <span class="nearby-phase" :class="`is-${phase}`" :title="statusHint">
          <span class="nearby-phase-dot" aria-hidden="true"></span>{{ status }}
        </span>
        <span v-if="rows.length" class="nearby-count-inline">{{ rows.length }} 只<span v-if="search.trim()"> / 已观察 {{ data?.actors.length ?? 0 }} 只</span></span>
      </div>
      <span class="nearby-count-note" :class="{ 'is-stale': stale }" :title="countNoteTitle" role="status">{{ countNote }}</span>
    </header>
    <div v-if="floatingError || (error && !stale) || (data && !data.mapping_available)" class="nearby-notices">
      <p v-if="floatingError" class="nearby-error" role="alert">{{ floatingError }}</p>
      <p v-if="error && !stale" class="nearby-error" role="alert">{{ error }}。当前无可用数据，请刷新重试。</p>
      <p v-if="data && !data.mapping_available" class="nearby-warning" role="status" title="精灵映射表未加载，名称、头像及体型参考标识可能缺失；原始观察数据仍会保留。">部分精灵资料缺失</p>
    </div>
    <div class="nearby-toolbar">
      <label class="nearby-search"><UiIcon name="search" /><input v-model="search" type="search" aria-label="搜索附近精灵" placeholder="搜索名称、配置或实体编号"></label>
      <label class="nearby-sort">排序<select v-model="sort" aria-label="附近精灵排序"><option value="recent">最近观察</option><option value="marks">有牌优先</option></select></label>
      <button class="ghost-button small nearby-refresh" :aria-busy="refreshing" :aria-disabled="refreshing" @click="refresh"><UiIcon name="refresh" />刷新</button>
      <button class="ghost-button small nearby-floating" @click="openFloating"><UiIcon name="eye" />悬浮雷达</button>
    </div>
    <div class="nearby-workspace">
      <div ref="listViewport" class="nearby-list-pane">
        <section v-if="rows.length" class="nearby-grid" aria-label="附近精灵列表" :aria-busy="loading">
          <div class="nearby-virtual-space" :style="{ height: `${virtualHeight}px` }">
            <article v-for="entry in virtualCards" :key="`${data?.observation_id}:${entry.actor.actor_id}`" :ref="measureRow" class="nearby-card nearby-virtual-row" :class="{ 'is-selected': selected === entry.actor.actor_id }" :data-index="entry.item.index" :id="`nearby-actor-${entry.actor.actor_id}`" tabindex="0" role="button" :aria-pressed="selected === entry.actor.actor_id" :style="{ transform: `translateY(${entry.item.start}px)` }" @click="selected = entry.actor.actor_id" @keydown.enter="selected = entry.actor.actor_id" @keydown.space.prevent="selected = entry.actor.actor_id">
              <div class="nearby-portrait"><img v-if="entry.actor.icon_url && !failedImages.has(entry.actor.icon_url)" :src="entry.actor.icon_url" alt="" loading="lazy" @error="imageFailed(entry.actor.icon_url)"><UiIcon v-else name="eye" /></div>
              <div class="nearby-card-copy">
                <div class="nearby-card-title">
                  <h3 :title="entry.actor.name">{{ entry.actor.name }}</h3>
                  <span class="nearby-level">Lv.{{ entry.actor.level ?? '?' }}</span>
                  <div class="nearby-types"><template v-for="type in entry.actor.type_names" :key="type"><img v-if="data?.type_icons[type]" class="nearby-type-icon" :src="data.type_icons[type]" :alt="type" :title="type" loading="lazy"><span v-else>{{ type }}</span></template><span v-if="!entry.actor.type_names.length">属性未知</span></div>
                  <div class="nearby-card-marks" :class="{ 'is-empty': !entry.actor.marks.length && entry.actor.attention !== 'double' }" aria-label="精灵标记"><template v-for="mark in entry.actor.marks" :key="mark.name"><MedalIcon v-if="isMedalMark(mark)" :name="mark.name" :source="mark.source" /><span v-else class="nearby-reference-mark" :title="`${mark.name} · 数值参考`">{{ mark.name }}</span></template><span v-if="entry.actor.attention === 'double'" class="nearby-double-mark" title="体型与声音均命中当前参考线，尚未确认游戏奖牌">双牌</span></div>
                </div>
                <p class="nearby-card-meta"><span>身高 <b>{{ metric(entry.actor.height, 100, 'm') }}</b></span><span aria-hidden="true">·</span><span>体重 <b>{{ metric(entry.actor.weight, 1000, 'kg') }}</b></span><span aria-hidden="true">·</span><span>音量 <b>{{ entry.actor.voice ?? '未知' }}</b></span></p>
                <footer><span class="nearby-entity" :title="`实体 ${entry.actor.actor_id}`">#{{ shortId(entry.actor.actor_id) }}</span><time :title="time(entry.actor.updated_at)">{{ relativeTime(entry.actor.updated_at) }}</time></footer>
              </div>
            </article>
          </div>
        </section>
        <section v-else class="nearby-empty" aria-live="polite">
          <span class="nearby-empty-icon"><UiIcon :name="initialLoading ? 'refresh' : 'eye'" /></span>
          <h3>{{ initialLoading ? '正在读取附近观察' : search.trim() ? '没有匹配的精灵' : '尚未观察到附近精灵' }}</h3>
          <p>{{ search.trim() ? '试试其他名称或编号。' : '进入场景并开始采集后会自动显示。' }}</p>
        </section>
      </div>
      <div class="nearby-radar-pane"><SceneRadar :data="data" :selected="selected" :radius="data?.radar_radius_raw" @select="selectActor" /></div>
    </div>
    <p class="nearby-footnote">只显示本次连接观察到的精灵，切号或切场景后清空；缺少位置的精灵仍保留在列表。</p>
  </div>
</template>

<style scoped>
/* 页面占满 app shell 的 `.page` 内容区：固定高度、内部滚动，避免整页纵向滚动把雷达裁掉。 */
:global(#nearby-root) { display: flex; height: 100%; min-height: 0; }
.nearby-page { display: flex; flex-direction: column; flex: 1; gap: var(--space-3); min-height: 0; min-width: 0; color: var(--ink); }
.nearby-heading { display: flex; align-items: center; justify-content: space-between; gap: var(--space-4); flex-wrap: wrap; }
.nearby-heading-main { display: flex; align-items: baseline; gap: var(--space-3); flex-wrap: wrap; min-width: 0; }
/* 顶栏已经显示页面名，重复的大标题只留给读屏，避免同一屏出现两次「附近精灵」。 */
.nearby-phase { display: inline-flex; align-items: center; gap: 6px; font-size: var(--fs-xs); color: var(--muted); min-width: 0; }
.nearby-phase-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--teal); flex: none; }
.nearby-phase.is-battle_unverified .nearby-phase-dot, .nearby-phase.is-disconnected .nearby-phase-dot, .nearby-phase.is-stopped .nearby-phase-dot, .nearby-phase.is-awaiting_identity .nearby-phase-dot { background: var(--amber); }
/* 计数并进状态行：空列表时不显示「0 只」，少一行零散文字。 */
.nearby-count-inline { color: var(--ink); font-size: var(--fs-xs); font-variant-numeric: tabular-nums; }
.nearby-count-inline span { color: var(--muted); font-weight: normal; }
.nearby-notices { display: flex; flex-direction: column; gap: var(--space-2); }
.nearby-toolbar { display: flex; align-items: center; gap: var(--space-3); flex-wrap: wrap; min-width: 0; }
.nearby-search { display: flex; align-items: center; gap: var(--space-3); flex: 1 1 240px; min-width: 0; border: 1px solid var(--line); border-radius: 999px; background: var(--panel); padding-inline: var(--space-4); }
/* 搜索框用胶囊圆角：与同排的胶囊状态一致，只是外壳圆角，不改输入框本身。 */
.nearby-search input { width: 100%; min-width: 0; border: 0; background: none; height: 34px; color: var(--ink); }
.nearby-search:focus-within { outline: 2px solid var(--focus-ring); outline-offset: 2px; }
.nearby-sort { display: flex; align-items: center; gap: var(--space-2); font-size: var(--fs-xs); min-width: 0; max-width: 100%; }
.nearby-sort select { min-width: 0; max-width: 100%; min-height: 34px; background: var(--panel); color: var(--ink); border: 1px solid var(--line); border-radius: var(--radius-sm); padding-inline: var(--space-3); }
.nearby-refresh, .nearby-floating { background: var(--panel); border: 1px solid var(--teal); color: var(--teal-dark); min-height: 34px; min-width: 0; max-width: 100%; white-space: normal; }
.nearby-count-note { flex: 0 1 auto; min-width: 0; text-align: right; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: var(--fs-xs); color: var(--muted); }
/* 状态文案固定单行且常驻在标题右侧：失败提示出现/消失不改变布局，避免内容区跳动；超窄视口截断，完整文案见 title。 */
.nearby-count-note.is-stale { padding: 0 var(--space-2); border-radius: var(--radius-sm); background: var(--amber-soft); color: var(--amber-ink); }
.nearby-workspace { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(300px, .85fr); gap: var(--space-4); flex: 1; min-height: 0; }
.nearby-list-pane { min-width: 0; min-height: 0; overflow-y: auto; padding: 2px; }
.nearby-radar-pane { display: flex; min-width: 0; min-height: 0; }
.nearby-radar-pane > * { flex: 1; min-width: 0; min-height: 0; }
.nearby-grid { min-width: 0; container-type: inline-size; }
.nearby-virtual-space { position: relative; min-width: 0; }
.nearby-virtual-row { position: absolute; inset: 0 0 auto; }
.nearby-card { display: flex; align-items: flex-start; gap: var(--space-3); min-width: 0; padding: calc(var(--space-3) + 2px) var(--space-4); background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius-sm); cursor: pointer; }
.nearby-card:hover { background: var(--surface-2); }
.nearby-card.is-selected, .nearby-card:focus-visible { outline: 2px solid var(--focus-ring); outline-offset: -2px; }
.nearby-portrait { display: grid; place-items: center; flex: none; width: 48px; height: 48px; background: var(--surface-2); border-radius: var(--radius-sm); color: var(--muted); }
.nearby-portrait img { width: 100%; height: 100%; object-fit: contain; }
.nearby-card-copy { display: flex; flex-direction: column; gap: 3px; flex: 1; min-width: 0; }
.nearby-card-title { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2); min-width: 0; }
.nearby-card h3 { min-width: 0; max-width: 100%; margin: 0; overflow: hidden; font-size: var(--fs-sm); font-weight: 700; line-height: 1.35; flex: 0 1 auto; text-overflow: ellipsis; white-space: nowrap; }
.nearby-level { color: var(--muted); font-size: var(--fs-xs); font-variant-numeric: tabular-nums; }
.nearby-types { display: flex; flex-wrap: wrap; gap: var(--space-1); }
.nearby-types span { background: var(--surface-2); color: var(--muted); border-radius: var(--radius-sm); padding: 0 var(--space-2); font-size: var(--fs-2xs); line-height: 1.7; }
.nearby-type-icon { width: 18px; height: 18px; flex: none; }
.nearby-card-marks { display: flex; align-items: center; gap: var(--space-1); margin-left: auto; height: 24px; min-width: 0; }
.nearby-card-marks > * { flex-shrink: 0; }
.nearby-card-marks.is-empty { display: none; }
.nearby-card-marks .medal-icon { width: 22px; height: 22px; }
.nearby-reference-mark, .nearby-double-mark { display: inline-flex; align-items: center; min-height: 20px; padding: 0 var(--space-2); border: 1px solid var(--amber-line); border-radius: var(--radius-sm); background: var(--amber-soft); color: var(--amber-ink); font-size: var(--fs-2xs); font-weight: 700; white-space: nowrap; }
.nearby-double-mark { border-color: var(--teal); background: var(--accent); color: var(--teal-deep); }
.nearby-card-meta { display: flex; align-items: baseline; gap: var(--space-1); margin: 0; min-width: 0; overflow: hidden; color: var(--muted); font-size: var(--fs-xs); white-space: nowrap; text-overflow: ellipsis; }
.nearby-card-meta b { color: var(--ink); font-weight: 600; font-variant-numeric: tabular-nums; }
.nearby-card footer { display: flex; align-items: baseline; justify-content: space-between; gap: var(--space-3); min-width: 0; padding: 0; border: 0; color: var(--muted); font-size: var(--fs-2xs); font-variant-numeric: tabular-nums; }
.nearby-entity { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.nearby-card time { flex: none; }
.nearby-empty { height: 100%; min-height: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: var(--space-2); padding: var(--space-6); text-align: center; border: 0; border-radius: var(--radius-sm); background: var(--panel); }
.nearby-empty-icon { display: grid; place-items: center; width: 44px; height: 44px; border-radius: 50%; background: var(--surface-2); color: var(--muted); }
.nearby-empty-icon .ui-icon { width: 20px; height: 20px; }
.nearby-empty h3 { font-size: var(--fs-md); margin: 0; }
.nearby-empty p { max-width: 36ch; }
.nearby-empty p, .nearby-footnote { margin: 0; color: var(--muted); line-height: 1.6; }
.nearby-footnote { font-size: var(--fs-2xs); }
.nearby-error, .nearby-warning { margin: 0; padding: var(--space-1) var(--space-3); border-radius: var(--radius-sm); font-size: var(--fs-xs); line-height: 1.5; }
.nearby-error { background: var(--danger-soft); color: var(--danger-ink); }
.nearby-warning { background: var(--amber-soft); color: var(--amber-ink); }
.nearby-page :is(p, h3, span, dd, strong) { overflow-wrap: anywhere; }
@media(max-width:1024px) { .nearby-workspace { grid-template-columns: minmax(0, 1fr) 280px; } }
/* 窄窗改为单列且列表在前：雷达不再挤占首屏主位。 */
@media(max-width:820px) {
  :global(#nearby-root) { height: auto; }
  .nearby-page { height: auto; }
  .nearby-workspace { grid-template-columns: minmax(0, 1fr); }
  .nearby-list-pane { height: min(62vh, 520px); }
  .nearby-radar-pane { height: 340px; }
}
@media(max-width:480px) {
  .nearby-toolbar .nearby-search { flex-basis: 100%; }
  .nearby-card { padding: var(--space-2) var(--space-3); }
  .nearby-portrait { width: 40px; height: 40px; }
}
</style>
