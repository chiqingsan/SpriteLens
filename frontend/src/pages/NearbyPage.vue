<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch, type ComponentPublicInstance } from 'vue'
import { useVirtualizer } from '@tanstack/vue-virtual'
import PageShell from '../components/PageShell.vue'
import UiIcon from '../components/UiIcon.vue'
import UiSearch from '../components/UiSearch.vue'
import UiSelect from '../components/UiSelect.vue'
import MedalIcon from '../components/MedalIcon.vue'
import SceneRadar from '../components/SceneRadar.vue'
import SceneMap from '../components/SceneMap.vue'
import { useNearby, type NearbyHost } from '../composables/useNearby'
import { useWorldMaps } from '../composables/useWorldMaps'
import type { NearbyActor, NearbyMark } from '../types/nearby'
import { usableWorldMap, type WorldMapEntry } from '../types/worldMap'

const props = defineProps<{ host: NearbyHost }>()
/** 游戏内炫彩标记（彩虹星），与雷达点位、悬浮条共用同一份本地素材。 */
const RARITY_COLORFUL = '/static/rarity/colorful-fit.webp'
const { data, summary, loading, error, stale, load, update, pause, resume } = useNearby(props.host)
const initialLoading = computed(() => loading.value && !data.value && !error.value)
// 提醒音开关由壳层持有并负责试听，Vue 只镜像 toggle 返回的状态；旧壳层没有 alert 时整枚按钮不渲染。
const alertHost = props.host.alert
const alertOn = ref(alertHost ? alertHost.enabled() : false)
function toggleAlert() { if (!alertHost) return; alertOn.value = alertHost.toggle(!alertOn.value) }
const selected = ref(''), floatingError = ref('')
const refreshing = ref(false)
async function refresh() {
  if (refreshing.value) return
  refreshing.value = true
  try { await load() } finally { refreshing.value = false }
}
// 清除足迹以服务端确认快照为准，避免超时或切换归属时恢复过期数据。
const clearingCoverage = ref(false), coverageError = ref('')
const canClearCoverage = computed(() => Boolean(props.host.resetCoverage) && Boolean(data.value?.coverage) && !clearingCoverage.value)
async function clearCoverage() {
  if (!canClearCoverage.value || !props.host.resetCoverage || !data.value?.resource_id) return
  const snapshot = data.value
  const reset = props.host.resetCoverage
  clearingCoverage.value = true
  coverageError.value = ''
  try {
    await reset({ uid: snapshot!.uid, resource_id: snapshot!.resource_id!, observation_id: snapshot!.observation_id })
  } catch (cause) {
    if (summary.value?.uid !== snapshot?.uid || summary.value?.observation_id !== snapshot?.observation_id) {
      clearingCoverage.value = false
      return
    }
    coverageError.value = cause instanceof Error ? cause.message : String(cause)
    // 超时不代表服务端未执行；重新读取以确认，且不恢复旧账号快照。
    try { await load() } finally { clearingCoverage.value = false }
    return
  }
  if (summary.value?.uid !== snapshot?.uid || summary.value?.observation_id !== snapshot?.observation_id) {
    clearingCoverage.value = false
    return
  }
  try { await load() } finally { clearingCoverage.value = false }
}
watch(data, snapshot => { if (!snapshot?.actors.some(actor => actor.actor_id === selected.value)) selected.value = '' })
async function openFloating() {
  floatingError.value = ''
  try { await props.host.openFloating?.() } catch (cause) { floatingError.value = cause instanceof Error ? cause.message : String(cause) }
}
async function selectActor(id: string) {
  selected.value = id; await nextTick()
  const index = rows.value.findIndex(row => row.actor_id === id)
  if (index >= 0) rowVirtualizer.value.scrollToIndex(index, { align: 'auto' })
  await nextTick()
  document.getElementById(`nearby-actor-${id}`)?.scrollIntoView({ block: 'nearest', behavior: 'auto' })
}
const search = ref(''), sort = ref('marks'), failedImages = ref(new Set<string>())
const sortOptions = [{ value: 'recent', label: '最近观察' }, { value: 'marks', label: '有牌优先' }]
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
  const compare = sort.value === 'marks'
    ? (a: NearbyActor, b: NearbyActor) => attentionRank(a) - attentionRank(b) || recent(a, b)
    : recent
  // 炫彩是游戏内固有外观：两种排序下都置顶，组内再按当前排序规则比较。
  return filtered.sort((a, b) => Number(b.colorful === true) - Number(a.colorful === true) || compare(a, b))
})
// 计数并进列表头：空列表不显示「0 只」，搜索时给出「结果 / 总数」。
const countLabel = computed(() => {
  const total = data.value?.actors.length ?? 0
  if (!total) return ''
  return search.value.trim() && rows.value.length !== total ? `${rows.value.length} / ${total} 只` : `${rows.value.length} 只`
})
const listViewport = ref<HTMLElement | null>(null)
const rowVirtualizerOptions = computed(() => ({
  count: rows.value.length,
  getScrollElement: () => listViewport.value,
  // 估计值取「名称行 + 标记行 + 三列数值」常见卡片实测高度（89~112）；实际高度仍由 measureRow 校正。
  estimateSize: () => 96,
  getItemKey: (index: number) => rows.value[index]?.actor_id ?? index,
  gap: 8,
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
const phase = computed(() => summary.value?.phase || 'awaiting_identity')
const battleStale = computed(() => Boolean(data.value && (data.value.position_source === 'battle_return' || data.value.actors.some(actor => actor.stale))))
// 页面级说明统一收进雷达面板底部，避免页面左右两端各挂一句零散文字。
const radarNote = '只显示本次连接观察到的精灵，切号或切场景后清空；缺少位置的精灵仍保留在列表。'
const { catalog: mapCatalog, error: mapsError, refresh: refreshMaps, stop: stopMaps } = useWorldMaps(props.host.loadMaps)
const sceneKey = computed(() => `${data.value?.resource_id ?? ''}:${data.value?.instance_id ?? ''}`)
// 雷达也使用底图，清单在页面进入时加载一次。
void refreshMaps()
const currentMap = computed<WorldMapEntry | null>(() => usableWorldMap(mapCatalog.value, data.value?.resource_id ?? null))
// 断流后保留静态底图供浏览；切到其它场景则不能继续显示上一张图。
const lastMap = ref<WorldMapEntry | null>(null)
const lastMapKey = ref('')
const lastMapData = ref<typeof data.value>(null)
watch(() => summary.value?.uid, uid => {
  if (uid && lastMapData.value && uid !== lastMapData.value.uid) {
    lastMap.value = null; lastMapKey.value = ''; lastMapData.value = null
  }
})
watch(data, snapshot => {
  if (snapshot?.resource_id && snapshot.phase === 'observing') lastMapData.value = snapshot
})
// 场景切换会先清空 data 再加载；只看 currentMap 变化会把「刷新中」误判成「换到无地图场景」，
// 所以同时观察 resource_id，只在明确拿到新场景且没有可用地图时退回雷达。
watch(currentMap, map => {
  if (map) {
    lastMap.value = map
    lastMapKey.value = sceneKey.value
    return
  }
})
// 断流与停采是合法的只读回看态：最后一份地图、覆盖与足迹继续保留，只是不再标成实时；
// 切场景、战斗或切号的等待期仍不能展示上一场景的底图。
const readOnlyPhase = computed(() => phase.value === 'disconnected' || phase.value === 'stopped')
const stoppedNote = computed(() => {
  if (!data.value) return ''
  if (phase.value === 'stopped') return '采集已停止，地图与本次足迹保留'
  if (phase.value === 'disconnected') return '连接已断开，显示最后一份观察'
  return ''
})
const displayMap = computed<WorldMapEntry | null>(() => currentMap.value
  ?? (readOnlyPhase.value || (data.value === null && summary.value === null) ? lastMap.value : null))
const viewMode = computed(() => displayMap.value ? 'map' : 'radar')
const displayMapKey = computed(() => (currentMap.value ? sceneKey.value : lastMapKey.value))
const displayMapData = computed(() => {
  if (!readOnlyPhase.value) return data.value
  const last = lastMapData.value
  if (!last || last.uid !== summary.value?.uid) return data.value
  return { ...last, actors: [], player_position: null, position_source: null }
})
onUnmounted(stopMaps)
const countNote = computed(() => {
  if (floatingError.value) return floatingError.value
  if (error.value && !stale.value) return '读取失败，请刷新重试'
  if (coverageError.value) return '清除足迹失败，请重试'
  if (summary.value?.coverage_error) return '搜索记录异常'
  if (stoppedNote.value) return stoppedNote.value
  if (battleStale.value) return '战前观察可能已过期'
  if (data.value && !data.value.mapping_available) return '部分精灵资料缺失'
  if (stale.value) return '刷新失败，显示的是稍早的结果'
  if (data.value?.coverage_paused) return '记录已暂停'
  return ''
})
const countNoteTitle = computed(() => {
  if (floatingError.value) return floatingError.value
  if (error.value && !stale.value) return `${error.value}。当前无可用数据，请刷新重试。`
  if (coverageError.value) return `清除足迹结果未确认：${coverageError.value}。请检查当前足迹后重试。`
  if (summary.value?.coverage_error) return `搜索记录异常：${summary.value.coverage_error}`
  if (stoppedNote.value) {
    return readOnlyPhase.value && phase.value === 'stopped'
      ? '服务器已停止采集本周期附近数据；地图、覆盖范围与本次足迹继续保留，可继续浏览，重新开始采集后恢复实时更新。'
      : '与游戏的连接已断开；展示的是断开前最后一份附近观察，重新连接后恢复实时更新。'
  }
  if (battleStale.value) return '战斗结束后接续的战前位置或精灵尚未重新确认，可能已过期。'
  if (data.value && !data.value.mapping_available) return '精灵映射表未加载，名称、头像及体型参考标识可能缺失；原始观察数据仍会保留。'
  if (stale.value) return `刷新失败，显示的是稍早的结果${error.value ? '：' + error.value : ''}`
  if (data.value?.coverage_paused) return '服务器下发范围尚待实测，当前不会记录搜索覆盖；附近精灵仍正常显示。'
  return '雷达外环按 1 原始单位 ≈ 1 cm 折算为米制（大陆现场校准，平面距离）'
})
function time(value: number | null) { return value === null ? '尚无更新' : new Date(value * 1000).toLocaleTimeString('zh-CN', { hour12: false }) }
const now = ref(Date.now())
const clockTimer = window.setInterval(() => { now.value = Date.now() }, 60000)
onUnmounted(() => window.clearInterval(clockTimer))
function relativeTime(value: number | null) {
  if (value === null) return '尚无更新'
  const seconds = Math.max(0, Math.floor(now.value / 1000 - value))
  if (seconds < 60) return '刚刚'
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`
  return time(value)
}
function metric(value: number | null, divisor: number, unit: string) { return value === null ? '未知' : `${(value / divisor).toLocaleString('zh-CN', { maximumFractionDigits: 3 })} ${unit}` }
function imageFailed(id: string) { failedImages.value = new Set(failedImages.value).add(id) }
function measureRow(element: Element | ComponentPublicInstance | null) {
  if (element instanceof HTMLElement) rowVirtualizer.value.measureElement(element)
}
onUnmounted(pause)
defineExpose({ update, load, pause, resume })
</script>

<template>
  <PageShell class="nearby-page">
    <template #toolbar>
      <div class="nearby-toolbar">
        <UiSearch v-model="search" class="nearby-search" label="搜索附近精灵" placeholder="搜索名称、配置或实体编号" />
        <UiSelect class="nearby-sort" :options="sortOptions" :model-value="sort" label="附近精灵排序" @change="sort = $event === 'marks' ? 'marks' : 'recent'" />
        <button class="ghost-button small nearby-refresh" :aria-busy="refreshing" :aria-disabled="refreshing" :disabled="refreshing" @click="refresh"><UiIcon name="refresh" />刷新</button>
        <button class="ghost-button small nearby-floating" @click="openFloating"><UiIcon name="eye" />悬浮雷达</button>
        <button v-if="alertHost" class="ghost-button small nearby-alert" type="button" :aria-pressed="alertOn" :title="alertOn ? '发现双牌重点精灵时播放提示音；点击关闭' : '声音提醒已关闭；点击开启并试听'" @click="toggleAlert"><UiIcon :name="alertOn ? 'bell' : 'bell-off'" />提醒音{{ alertOn ? '开' : '关' }}</button>
        <button v-if="host.resetCoverage" class="ghost-button small nearby-clear-coverage" type="button" :disabled="!canClearCoverage" :aria-busy="clearingCoverage || undefined" title="清除当前地图的本次足迹；只影响覆盖层，不重置附近列表与观察周期" @click="clearCoverage"><UiIcon name="trash" />清除足迹</button>
        <button v-if="mapsError" type="button" class="ghost-button small" @click="refreshMaps"><UiIcon name="refresh" />重试地图清单</button>
      </div>
    </template>
    <div class="nearby-workspace" :class="{ 'is-map': viewMode === 'map' }">
      <div class="nearby-list-panel">
        <header class="nearby-list-header">
          <h3>附近观察</h3>
          <span class="nearby-count-note" :class="{ 'is-stale': stale || battleStale, 'is-error': error && !stale || floatingError || coverageError || summary?.coverage_error, 'is-warning': Boolean(stoppedNote) || Boolean(data && (!data.mapping_available || data.coverage_paused)) }" :title="countNoteTitle" role="status">{{ countNote }}</span>
          <span v-if="countLabel" class="nearby-list-count">{{ countLabel }}</span>
        </header>
        <div ref="listViewport" class="nearby-list-pane">
        <section v-if="rows.length" class="nearby-grid" aria-label="附近精灵列表" :aria-busy="loading">
          <div class="nearby-virtual-space" :style="{ height: `${virtualHeight}px` }">
            <article v-for="entry in virtualCards" :key="entry.actor.actor_id" :ref="measureRow" class="nearby-card nearby-virtual-row" :class="{ 'is-selected': selected === entry.actor.actor_id, 'is-colorful': entry.actor.colorful }" :data-index="entry.item.index" :id="`nearby-actor-${entry.actor.actor_id}`" tabindex="0" role="button" :aria-pressed="selected === entry.actor.actor_id" :style="{ transform: `translateY(${entry.item.start}px)` }" @click="selected = entry.actor.actor_id" @keydown.enter="selected = entry.actor.actor_id" @keydown.space.prevent="selected = entry.actor.actor_id">
              <div class="nearby-portrait"><img v-if="entry.actor.icon_url && !failedImages.has(entry.actor.icon_url)" :src="entry.actor.icon_url" alt="" loading="lazy" @error="imageFailed(entry.actor.icon_url)"><UiIcon v-else name="eye" /><img v-if="entry.actor.colorful" class="nearby-portrait-colorful" :src="RARITY_COLORFUL" alt="" loading="lazy"></div>
              <div class="nearby-card-copy">
                <div class="nearby-card-top">
                  <div class="nearby-card-identity">
                    <h3 :title="entry.actor.name">{{ entry.actor.name }}</h3>
                    <span class="nearby-level nearby-level-lv">Lv.{{ entry.actor.level ?? '?' }}</span>
                    <span v-if="entry.actor.stale" class="nearby-level nearby-level-stale" title="战前观察，尚未重新确认">可能已过期</span>
                    <div class="nearby-types"><template v-for="type in entry.actor.type_names" :key="type"><span class="nearby-type-chip"><img v-if="data?.type_icons[type]" class="nearby-type-icon" :src="data.type_icons[type]" :alt="type" loading="lazy">{{ type }}</span></template><span v-if="!entry.actor.type_names.length" class="nearby-type-chip">属性未知</span></div>
                  </div>
                  <time class="nearby-time" :title="entry.actor.updated_at === null ? '尚无更新' : '观察于 ' + time(entry.actor.updated_at)">{{ relativeTime(entry.actor.updated_at) }}</time>
                </div>
                <div class="nearby-card-marks" :class="{ 'is-empty': !entry.actor.colorful && !entry.actor.marks.length && entry.actor.attention !== 'double' }" aria-label="精灵标记">
                  <span v-if="entry.actor.colorful" class="nearby-colorful-mark" title="游戏内炫彩外观（变异类型标记），与本地奖牌参考线无关"><img :src="RARITY_COLORFUL" alt="" loading="lazy">炫彩</span>
                  <span v-if="entry.actor.attention === 'double'" class="nearby-double-mark" title="体型与声音均命中当前参考线，尚未确认游戏奖牌">双牌</span>
                  <template v-for="mark in entry.actor.marks" :key="mark.name"><MedalIcon v-if="isMedalMark(mark)" :name="mark.name" :source="mark.source" /><span v-else class="nearby-reference-mark" :title="`${mark.name} · 数值参考`">{{ mark.name }}</span></template>
                </div>
                <p class="nearby-card-meta"><span>身高 <b>{{ metric(entry.actor.height, 100, 'm') }}</b></span><span>体重 <b>{{ metric(entry.actor.weight, 1000, 'kg') }}</b></span><span>音量 <b>{{ entry.actor.voice ?? '未知' }}</b></span></p>
              </div>
            </article>
          </div>
        </section>
        <section v-else class="nearby-empty" :aria-live="error && !stale ? 'assertive' : 'polite'">
          <template v-if="error && !stale">
            <span class="nearby-empty-icon"><UiIcon name="refresh" /></span>
            <h3>附近数据读取失败</h3>
            <p>{{ error }}。检查本地服务后重试。</p>
            <button type="button" class="ghost-button small nearby-retry" :aria-busy="refreshing" :disabled="refreshing" @click="refresh"><UiIcon name="refresh" />重试</button>
          </template>
          <template v-else>
            <span class="nearby-empty-icon"><UiIcon :name="initialLoading ? 'refresh' : 'eye'" /></span>
            <h3>{{ initialLoading ? '正在读取附近观察' : search.trim() ? '没有匹配的精灵' : '尚未观察到附近精灵' }}</h3>
            <p>{{ search.trim() ? '试试其他名称或编号。' : '进入场景并开始采集后会自动显示。' }}</p>
          </template>
        </section>
        </div>
      </div>
      <div class="nearby-radar-pane">
        <div class="nearby-view">
            <SceneMap v-if="displayMap" :visible="true" :data="displayMapData" :map="displayMap" :selected="selected" :scene-key="displayMapKey" @select="selectActor" />
          <SceneRadar v-else :data="data" :map="currentMap" :selected="selected" :radius="data?.radar_radius_raw" :note="radarNote" @select="selectActor" />
        </div>
      </div>
    </div>
  </PageShell>
</template>

<style scoped>
/* 页面占满 app shell 的 `.page` 内容区：固定高度、内部滚动，避免整页纵向滚动把雷达裁掉。 */
:global(#nearby-root) { display: flex; height: 100%; min-height: 0; }
.nearby-page { display: flex; flex-direction: column; flex: 1; gap: var(--space-3); min-height: 0; min-width: 0; color: var(--ink); container: nearby / inline-size; }
/* 工具条只有一行操作区（状态与计数已并入列表头），沿用 PageShell 的横向布局。 */
.nearby-page :deep(.ui-page-toolbar) { gap: var(--space-3); min-width: 0; padding: 0; border-bottom: 0; }
.nearby-toolbar { display: flex; align-items: center; gap: var(--space-3); flex: 1 1 auto; flex-wrap: wrap; min-width: 0; }
/* 外观统一由 .ui-search 承担；这里只决定它在工具条里的伸缩比例（原先的 999px 胶囊与同排 10px 圆角按钮不一致） */
.nearby-search { flex: 1 1 240px; min-width: 0; }
.nearby-sort { min-width: 0; max-width: 100%; font-size: var(--fs-xs); }
.nearby-refresh, .nearby-floating { background: var(--panel); border: 1px solid var(--teal); color: var(--teal-dark); min-height: 34px; min-width: 0; max-width: 100%; white-space: normal; }
/* 提醒音是偏好项，固定在工具条末尾。开/关都显示四个汉字、图标盒同为 18px，切换只换底色/描边，不改变按钮尺寸。 */
.nearby-alert { background: var(--panel); border: 1px solid var(--line); color: var(--ink); min-height: 34px; min-width: 0; max-width: 100%; white-space: nowrap; }
.nearby-alert:hover { background: var(--surface-2); border-color: var(--muted); }
/* 开启态沿用重点标识配色（accent 底 + 深字 + teal 描边），与「双牌」标记同一语义。 */
.nearby-alert[aria-pressed='true'] { background: var(--accent); border-color: var(--teal); color: var(--teal-deep); }
.nearby-alert[aria-pressed='true']:hover { border-color: var(--teal-dark); }
/* 清除足迹是低频覆盖层操作，用中性描边避免与左侧主动作抢视觉；无足迹时禁用。 */
.nearby-clear-coverage { background: var(--panel); border: 1px solid var(--line); color: var(--ink); min-height: 34px; min-width: 0; max-width: 100%; white-space: nowrap; }
.nearby-clear-coverage:hover { background: var(--surface-2); border-color: var(--muted); }
/* 状态文案常驻在列表头中间：失败提示出现/消失不改变列表高度；超窄视口截断，完整文案见 title。 */
.nearby-count-note { flex: 0 1 auto; margin-left: auto; min-width: 0; max-width: 100%; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: var(--fs-xs); color: var(--muted); }
.nearby-count-note.is-stale { padding: 0 var(--space-2); border-radius: var(--radius-sm); background: var(--amber-soft); color: var(--amber-ink); }
.nearby-count-note.is-error { color: var(--danger-ink); }
.nearby-count-note.is-warning { color: var(--amber-ink); }
.nearby-workspace { display: grid; grid-template-columns: minmax(280px, .85fr) minmax(0, 1.15fr); gap: var(--space-4); flex: 1; min-height: 0; }
.nearby-list-panel { display: flex; flex-direction: column; min-width: 0; min-height: 0; border: 1px solid var(--line); border-radius: var(--radius-sm); background: var(--panel); }
.nearby-list-header { display: flex; align-items: center; gap: var(--space-2) var(--space-3); min-height: 44px; padding: 0 var(--space-4); border-bottom: 1px solid var(--line-soft); }
.nearby-list-header h3 { flex: none; margin: 0; font-size: var(--fs-md); font-weight: 600; }
.nearby-list-count { flex: none; color: var(--muted); font-size: var(--fs-xs); font-variant-numeric: tabular-nums; }
.nearby-list-pane { flex: 1; min-width: 0; min-height: 0; overflow-y: auto; scrollbar-gutter: stable; }
.nearby-radar-pane { display: flex; min-width: 0; min-height: 0; }
.nearby-radar-pane > * { flex: 1; min-width: 0; min-height: 0; }
.nearby-view { display: flex; flex-direction: column; min-width: 0; min-height: 0; }
/* 雷达/地图是同一份观察的两种视图；分段按钮保持 28px 高，切换不推动下方内容。 */
.nearby-view-switch { display: inline-flex; flex: none; gap: 2px; padding: 2px; border: 1px solid var(--line); border-radius: var(--radius-sm); background: var(--panel); }
.nearby-view-switch button { display: inline-flex; align-items: center; gap: 4px; min-height: 28px; padding: 0 var(--space-3); border: 0; border-radius: 4px; background: none; color: var(--muted); font-size: var(--fs-xs); font-weight: 700; cursor: pointer; }
.nearby-view-switch button:not(:disabled):is(:hover, :active) { transform: none; }
.nearby-view-switch button :deep(.ui-icon) { width: 14px; height: 14px; }
.nearby-view-switch button[aria-pressed='true'] { background: var(--accent); color: var(--teal-deep); font-weight: 700; }
.nearby-view-switch button:focus-visible { outline: 2px solid var(--focus-ring); outline-offset: 1px; }
.nearby-view > .scene-radar, .nearby-view > .scene-map, .nearby-view > .nearby-map-empty { flex: 1 1 0; min-height: 0; }
.nearby-map-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: var(--space-3); padding: var(--space-6); text-align: center; background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); }
.nearby-map-empty-icon { display: grid; place-items: center; width: 44px; height: 44px; border-radius: 50%; background: var(--surface-2); color: var(--muted); }
.nearby-map-empty-icon .ui-icon { width: 20px; height: 20px; }
.nearby-map-empty h3 { margin: 0; font-size: var(--fs-md); }
.nearby-map-empty p { margin: 0; max-width: 34ch; color: var(--muted); font-size: var(--fs-xs); line-height: 1.6; }
.nearby-map-empty-actions { display: flex; flex-wrap: wrap; align-items: center; justify-content: center; gap: var(--space-2); }
.nearby-grid { min-width: 0; padding: var(--space-3); container-type: inline-size; }
.nearby-virtual-space { position: relative; min-width: 0; }
/* 虚拟行必须脱离文档流：`.nearby-card` 自带 position 声明，这里用双类名保证覆盖顺序无关。 */
.nearby-card.nearby-virtual-row { position: absolute; inset: 0 0 auto; }
.nearby-card { position: relative; display: flex; align-items: flex-start; gap: var(--space-3); min-width: 0; padding: var(--space-3); background: var(--surface-1); border: 1px solid var(--line-soft); border-radius: var(--radius-md); cursor: pointer; }
.nearby-card:hover { background: var(--surface-2); border-color: var(--line); }
/* 选中/聚焦描边贴在卡片边框外沿，不压内部内容，也不会和炫彩边框叠成双线。 */
.nearby-card.is-selected, .nearby-card:focus-visible { outline: 2px solid var(--focus-ring); outline-offset: 0; }
/* 头像略大于文字行高，给名称/属性一个稳定的左侧锚点；炫彩卡在头像外包彩虹环并挂游戏内星标。 */
.nearby-portrait { position: relative; display: grid; place-items: center; flex: none; width: 52px; height: 52px; background: var(--surface-2); border-radius: var(--radius-md); color: var(--muted); }
.nearby-portrait > img:not(.nearby-portrait-colorful) { width: 100%; height: 100%; border-radius: var(--radius-md); object-fit: contain; }
.nearby-portrait-colorful { position: absolute; right: -6px; bottom: -6px; width: 20px; height: 20px; object-fit: contain; filter: drop-shadow(0 1px 2px rgba(0, 0, 0, .4)); }
.nearby-card-copy { display: flex; flex-direction: column; gap: var(--space-1); flex: 1; min-width: 0; }
/* 身份行：名称/Lv/属性占左侧可换行区域，观察时间钉在右上角；属性再多也不会把时间挤走。 */
.nearby-card-top { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: start; column-gap: var(--space-3); min-width: 0; }
.nearby-card-identity { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-1) var(--space-2); min-width: 0; }
.nearby-card h3 { min-width: 0; max-width: 100%; margin: 0; overflow: hidden; font-size: var(--fs-lg); font-weight: 700; line-height: 1.35; flex: 0 1 auto; text-overflow: ellipsis; white-space: nowrap; }
.nearby-level { flex: none; color: var(--muted); font-size: var(--fs-3xs); line-height: 1.35; font-variant-numeric: tabular-nums; }
/* Lv 是稳定属性，用浅底胶囊与名称分隔；过期提示是警告文案，只用琥珀色不带底。 */
.nearby-level-lv { display: inline-flex; align-items: center; min-height: 20px; padding: 0 6px; border-radius: var(--radius-pill); background: var(--surface-2); }
.nearby-level-stale { color: var(--amber-ink); }
.nearby-types { display: flex; flex-wrap: wrap; gap: var(--space-1); min-width: 0; max-width: 100%; }
.nearby-type-chip { display: inline-flex; align-items: center; gap: 3px; min-height: 19px; max-width: 100%; padding: 0 6px; border: 1px solid var(--line-soft); border-radius: var(--radius-pill); background: var(--surface-2); color: var(--ink-soft); font-size: var(--fs-3xs); line-height: 1; white-space: nowrap; }
.nearby-type-icon { width: 13px; height: 13px; flex: none; object-fit: contain; border-radius: 50%; }
.nearby-time { flex: none; padding-top: 1px; color: var(--muted); font-size: var(--fs-3xs); line-height: 1.35; font-variant-numeric: tabular-nums; white-space: nowrap; }
/* 标记行始终占位（无标记时 .is-empty 隐藏），避免有无标记的卡片高度跳变。 */
.nearby-card-marks { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-1) var(--space-2); min-width: 0; max-width: 100%; min-height: 22px; }
.nearby-card-marks.is-empty { visibility: hidden; }
.nearby-card-marks > * { flex-shrink: 0; }
.nearby-card-marks .medal-icon { width: 22px; height: 22px; }
.nearby-reference-mark, .nearby-double-mark { display: inline-flex; align-items: center; min-height: 22px; padding: 0 var(--space-2); border: 1px solid var(--amber-line); border-radius: var(--radius-sm); background: var(--amber-soft); color: var(--amber-ink); font-size: var(--fs-3xs); font-weight: 700; white-space: nowrap; }
.nearby-double-mark { border-color: var(--teal); background: var(--accent); color: var(--teal-deep); }
/* 炫彩：游戏内固有外观（mutation 第 4 位），独立于本地奖牌参考线。
   用彩虹竖条 + 淡彩底 + 头像彩虹环 + 星标贴纸表达稀缺度，不再依赖虚线紫框。 */
/* 炫彩：游戏内固有外观（mutation 第 4 位），独立于本地奖牌参考线。
   稀有卡片用左浓右淡的紫雾底 + 头像彩虹环 + 右下角星标表达；不再压彩虹竖条，
   避免与选中/聚焦描边在同一圈位置上叠出双线。 */
.nearby-card.is-colorful { border-color: var(--colorful-line); background: linear-gradient(100deg, color-mix(in srgb, var(--colorful-soft) 72%, var(--surface-1)) 0%, color-mix(in srgb, var(--colorful-soft) 26%, var(--surface-1)) 54%, var(--surface-1) 82%); }
.nearby-card.is-colorful:hover { background: linear-gradient(100deg, color-mix(in srgb, var(--colorful-soft) 82%, var(--surface-2)) 0%, color-mix(in srgb, var(--colorful-soft) 30%, var(--surface-2)) 54%, var(--surface-2) 82%); }
.nearby-card.is-colorful .nearby-portrait { border: 2.5px solid transparent; background: linear-gradient(var(--surface-2), var(--surface-2)) padding-box, var(--colorful-gradient) border-box; }
.nearby-colorful-mark { display: inline-flex; align-items: center; gap: 3px; min-height: 22px; padding: 0 var(--space-2); border: 1px solid var(--colorful-line); border-radius: var(--radius-pill); background: var(--colorful-soft); color: var(--colorful-ink); font-size: var(--fs-3xs); font-weight: 700; white-space: nowrap; }
.nearby-colorful-mark img { width: 14px; height: 14px; flex: none; object-fit: contain; }
.nearby-card-meta { display: flex; align-items: baseline; flex-wrap: wrap; gap: var(--space-1) var(--space-4); margin: 0; min-width: 0; color: var(--muted); font-size: var(--fs-xs); line-height: 1.4; }
.nearby-card-meta > span { flex: none; white-space: nowrap; }
.nearby-card-meta b { color: var(--ink); font-weight: 600; font-variant-numeric: tabular-nums; }
.nearby-empty { height: 100%; min-height: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: var(--space-2); padding: var(--space-6); text-align: center; border: 0; border-radius: var(--radius-sm); background: var(--panel); }
.nearby-empty-icon { display: grid; place-items: center; width: 44px; height: 44px; border-radius: 50%; background: var(--surface-2); color: var(--muted); }
.nearby-empty-icon .ui-icon { width: 20px; height: 20px; }
.nearby-empty h3 { font-size: var(--fs-md); margin: 0; }
.nearby-empty p { max-width: 36ch; }
.nearby-empty p { margin: 0; color: var(--muted); line-height: 1.6; }
.nearby-page :is(p, h3, span, dd, strong) { overflow-wrap: anywhere; }
/* 页面实际可用宽度也响应缩放，避免高 DPI 时仍按物理窗口宽度挤两栏。 */
@container nearby (max-width: 620px) {
  /* 工具条在窄容器里允许收缩换行，避免按最大内容宽撑出横向滚动。 */
  .nearby-toolbar { flex: 1 1 auto; min-width: 0; max-width: 100%; }
  .nearby-workspace { grid-template-columns: minmax(0, 1fr); flex: none; }
  .nearby-radar-pane { order: -1; height: min(65vh, 480px); min-height: 280px; }
  .nearby-list-panel { height: min(62vh, 520px); min-height: 240px; }
}
@media(max-width:1024px) { .nearby-workspace { grid-template-columns: minmax(250px, .85fr) minmax(0, 1.15fr); } }
/* 窄窗改为单列且列表在前：雷达不再挤占首屏主位；地图是主动操作的结果，排到列表上方。 */
@media(max-width:820px) {
  :global(#nearby-root) { height: auto; }
  .nearby-page { height: auto; }
  .nearby-workspace { grid-template-columns: minmax(0, 1fr); }
  .nearby-list-panel { height: min(62vh, 520px); min-height: 240px; }
  .nearby-radar-pane { order: -1; height: min(65vh, 480px); min-height: 280px; }
}
@media(max-width:480px) {
  .nearby-toolbar .nearby-search { flex-basis: 100%; }
  .nearby-card { padding: var(--space-2) var(--space-3); }
  .nearby-portrait { width: 44px; height: 44px; }
  .nearby-card-meta { font-size: var(--fs-3xs); }
}
</style>
