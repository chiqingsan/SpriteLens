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
  // 搜索同时匹配进化链名称：搜「恶魔叮」也能看到链上的叮叮恶魔、恶魔男爵。
  const filtered = (data.value?.actors || []).filter(row => `${row.name} ${row.config_id ?? ''} ${row.actor_id} ${(row.chain_names || []).join(' ')}`.toLocaleLowerCase().includes(needle))
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
// 页面级说明统一收进雷达面板底部，避免页面左右两端各挂一句零散文字。
const radarNote = '只显示本次连接观察到的精灵，切号或切场景后清空；缺少位置的精灵仍保留在列表。'
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
      <div class="nearby-radar-pane"><SceneRadar :data="data" :selected="selected" :radius="data?.radar_radius_raw" :note="radarNote" @select="selectActor" /></div>
    </div>
  </div>
</template>

<style scoped>
/* 附近页：固定高度、列表单独滚动，雷达面板和列表等高，避免整页滚动裁掉雷达。 */
:global(#nearby-root) { display: flex; height: 100%; min-height: 0; }
.nearby-page { display: flex; flex: 1; flex-direction: column; gap: var(--space-3); min-width: 0; min-height: 0; color: var(--ink); }

.nearby-heading { display: flex; flex: none; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: var(--space-2) var(--space-4); min-height: 26px; }
.nearby-heading-main { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-3); min-width: 0; }
.nearby-phase { display: inline-flex; align-items: center; gap: var(--space-2); height: 26px; padding: 0 var(--space-3); border-radius: 999px; background: var(--surface-2); color: var(--ink-soft); font-size: var(--fs-2xs); font-weight: 500; white-space: nowrap; }
.nearby-phase-dot { width: 6px; height: 6px; flex: none; border-radius: 50%; background: var(--teal); box-shadow: 0 0 0 3px color-mix(in srgb, var(--teal) 14%, transparent); }
.nearby-phase.is-battle_unverified .nearby-phase-dot,
.nearby-phase.is-disconnected .nearby-phase-dot,
.nearby-phase.is-stopped .nearby-phase-dot,
.nearby-phase.is-resumed_stale .nearby-phase-dot,
.nearby-phase.is-awaiting_identity .nearby-phase-dot { background: var(--amber); box-shadow: 0 0 0 3px color-mix(in srgb, var(--amber) 18%, transparent); }
.nearby-count-inline { color: var(--ink); font-size: var(--fs-xs); font-weight: 600; font-variant-numeric: tabular-nums; }
.nearby-count-inline span { color: var(--muted); font-weight: 400; }
.nearby-count-note { flex: 0 1 auto; min-width: 0; overflow: hidden; color: var(--muted); font-size: var(--fs-2xs); text-align: right; text-overflow: ellipsis; white-space: nowrap; }
.nearby-count-note.is-stale { padding: 1px var(--space-2); border-radius: 999px; background: var(--amber-soft); color: var(--amber-ink); }

.nearby-notices { display: flex; flex: none; flex-direction: column; gap: var(--space-2); }
.nearby-error, .nearby-warning { margin: 0; padding: var(--space-2) var(--space-3); border-radius: var(--radius-md); font-size: var(--fs-xs); line-height: 1.5; overflow-wrap: anywhere; }
.nearby-error { border: 1px solid color-mix(in srgb, var(--danger) 26%, transparent); background: var(--danger-soft); color: var(--danger-ink); }
.nearby-warning { border: 1px solid var(--amber-line); background: var(--amber-soft); color: var(--amber-ink); }

.nearby-toolbar { display: flex; flex: none; flex-wrap: wrap; align-items: center; gap: var(--space-2); min-width: 0; }
.nearby-search { display: flex; flex: 1 1 240px; align-items: center; gap: var(--space-2); min-width: 0; height: 34px; padding-inline: var(--space-4); border: 1px solid var(--line); border-radius: 999px; background: var(--panel); }
.nearby-search .ui-icon { width: 15px; height: 15px; flex: none; color: var(--muted); }
.nearby-search input { width: 100%; min-width: 0; height: 30px; padding: 0; border: 0; background: none; color: var(--ink); font-size: var(--fs-xs); }
.nearby-search input::placeholder { color: var(--muted-2); }
.nearby-search:focus-within { border-color: var(--teal); box-shadow: 0 0 0 3px color-mix(in srgb, var(--teal) 14%, transparent); }
.nearby-sort { display: flex; align-items: center; gap: var(--space-2); min-width: 0; color: var(--muted); font-size: var(--fs-2xs); white-space: nowrap; }
.nearby-sort select { min-width: 0; max-width: 100%; height: 32px; padding: 0 28px 0 var(--space-3); border: 1px solid var(--line); border-radius: var(--radius-md); background-color: var(--panel); color: var(--ink-soft); font-size: var(--fs-xs); }
.nearby-sort select:focus-visible { outline: 2px solid var(--focus-ring); outline-offset: 1px; }
.nearby-refresh, .nearby-floating { height: 34px; min-height: 34px; padding: 0 var(--space-4); border-radius: 999px; font-size: var(--fs-xs); white-space: normal; }
.nearby-refresh { border: 1px solid var(--line); background: var(--panel); color: var(--ink-soft); }
.nearby-refresh:hover:not(:disabled) { border-color: var(--teal); background: var(--teal-soft); color: var(--teal-dark); }
.nearby-floating { border: 1px solid color-mix(in srgb, var(--teal) 45%, transparent); background: var(--teal-soft); color: var(--teal-dark); font-weight: 600; }
.nearby-floating:hover { border-color: var(--teal); background: color-mix(in srgb, var(--teal-soft) 72%, var(--accent)); }

.nearby-workspace { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(280px, .85fr); gap: var(--space-4); flex: 1 1 auto; min-width: 0; min-height: 0; }
.nearby-list-pane { min-width: 0; min-height: 0; overflow-y: auto; overscroll-behavior: contain; padding: 2px; scrollbar-gutter: stable; }
.nearby-radar-pane { display: flex; min-width: 0; min-height: 0; }
.nearby-radar-pane > * { flex: 1; min-width: 0; min-height: 0; }
.nearby-grid { display: block; min-width: 0; }
.nearby-virtual-space { position: relative; width: 100%; min-width: 0; }
.nearby-virtual-row { position: absolute; top: 0; left: 0; width: 100%; }

.nearby-card { display: flex; align-items: flex-start; gap: var(--space-3); min-width: 0; padding: var(--space-3) var(--space-4); border: 1px solid var(--line-soft); border-radius: var(--radius-lg); background: var(--panel); cursor: pointer; transition: background var(--motion-fast) var(--motion-ease), border-color var(--motion-fast) var(--motion-ease), box-shadow var(--motion-fast) var(--motion-ease); }
.nearby-card:hover { border-color: var(--line); background: var(--surface-1); box-shadow: var(--shadow-1); }
.nearby-card.is-selected,
.nearby-card:focus-visible { border-color: var(--teal); background: var(--teal-soft); box-shadow: inset 0 0 0 1px var(--teal); outline: none; }
.nearby-portrait { display: grid; flex: none; place-items: center; width: 48px; height: 48px; overflow: hidden; border-radius: var(--radius-md); background: var(--surface-2); color: var(--muted); }
.nearby-portrait img { width: 100%; height: 100%; object-fit: contain; }
.nearby-card-copy { display: flex; flex: 1; flex-direction: column; gap: var(--space-1); min-width: 0; }
.nearby-card-title { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-1) var(--space-2); min-width: 0; }
.nearby-card h3 { flex: 0 1 auto; max-width: 100%; min-width: 0; margin: 0; overflow: hidden; color: var(--ink); font-size: var(--fs-sm); font-weight: 600; line-height: 1.35; text-overflow: ellipsis; white-space: nowrap; }
.nearby-level { flex: none; color: var(--muted); font-size: var(--fs-3xs); font-variant-numeric: tabular-nums; }
.nearby-types { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-1); min-width: 0; }
.nearby-types > span { padding: 0 var(--space-2); border-radius: 999px; background: var(--surface-2); color: var(--muted); font-size: var(--fs-3xs); line-height: 18px; white-space: nowrap; }
.nearby-type-icon { width: 18px; height: 18px; flex: none; object-fit: contain; }
.nearby-card-marks { display: flex; align-items: center; gap: var(--space-1); margin-left: auto; min-width: 0; }
.nearby-card-marks.is-empty { display: none; }
.nearby-card-marks > * { flex: none; }
.nearby-reference-mark,
.nearby-double-mark { display: inline-flex; align-items: center; min-height: 20px; padding: 0 var(--space-2); border: 1px solid var(--amber-line); border-radius: 999px; background: var(--amber-soft); color: var(--amber-ink); font-size: var(--fs-3xs); font-weight: 600; white-space: nowrap; }
.nearby-double-mark { border-color: color-mix(in srgb, var(--teal) 45%, transparent); background: var(--teal-soft); color: var(--teal-deep); }
.nearby-card-meta { display: flex; flex-wrap: wrap; align-items: baseline; gap: 0 var(--space-1); min-width: 0; margin: 0; color: var(--muted); font-size: var(--fs-2xs); }
.nearby-card-meta b { color: var(--ink-soft); font-weight: 600; font-variant-numeric: tabular-nums; }
.nearby-card footer { display: flex; align-items: baseline; justify-content: space-between; gap: var(--space-3); min-width: 0; color: var(--muted-2); font-size: var(--fs-3xs); font-variant-numeric: tabular-nums; }
.nearby-entity { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.nearby-card time { flex: none; }

.nearby-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: var(--space-2); height: 100%; min-height: 180px; padding: var(--space-8); border: 1px dashed var(--line); border-radius: var(--radius-lg); background: var(--panel); text-align: center; }
.nearby-empty-icon { display: grid; place-items: center; width: 48px; height: 48px; border-radius: 50%; background: var(--surface-2); color: var(--muted); }
.nearby-empty-icon .ui-icon { width: 20px; height: 20px; }
.nearby-empty h3 { margin: 0; font-size: var(--fs-md); font-weight: 600; }
.nearby-empty p { max-width: 36ch; margin: 0; color: var(--muted); font-size: var(--fs-xs); line-height: 1.6; }

@media (max-width: 1200px) {
  .nearby-workspace { grid-template-columns: minmax(0, 1fr) minmax(320px, 340px); }
}
/* 雷达继续压到 280px 时 SVG 会缩到 0.7 倍、文字只剩 7px；并排布局下给雷达保底 320px，
   只有在更窄的窗口才改为上下排列，页面滚动由 .page 承担。 */
@media (max-width: 860px) {
  :global(#nearby-root) { display: block; height: auto; }
  .nearby-page { height: auto; }
  .nearby-workspace { grid-template-columns: minmax(0, 1fr); gap: var(--space-3); }
  .nearby-list-pane { height: min(62vh, 520px); }
  .nearby-radar-pane { height: 380px; }
}
@media (max-width: 480px) {
  .nearby-search { flex-basis: 100%; }
  .nearby-card { padding: var(--space-2) var(--space-3); }
  .nearby-portrait { width: 40px; height: 40px; }
}
</style>
