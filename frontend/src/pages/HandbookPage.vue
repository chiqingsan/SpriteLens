<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import type { ApiClient } from '../api/client'
import { useHandbook, type HandbookMode } from '../composables/useHandbook'
import type { HandbookSpecies } from '../types/handbook'
import { typeBadgeStyle } from '../components/handbookDisplay'
import HandbookDetail from '../components/HandbookDetail.vue'
import UiIcon from '../components/UiIcon.vue'

const props = defineProps<{ api: ApiClient; active: boolean }>()
const { filters, data, loading, error, load, pause, resume, resetAccount, clear } = useHandbook(props.api)

/* 分批渲染：一次最多 120 张富卡片，避免上千个节点同时入 DOM。 */
const PAGE_SIZE = 120
const limit = ref(PAGE_SIZE)
const shown = computed(() => data.value?.species.slice(0, limit.value) || [])
const remaining = computed(() => Math.max(0, (data.value?.species.length || 0) - shown.value.length))
function more() { limit.value += PAGE_SIZE * 2 }

const selected = ref<string | null>(null)
const item = computed(() => data.value?.species.find(row => row.key === selected.value))
const content = ref<HTMLElement>()
const closeButton = ref<HTMLButtonElement>()
const narrow = window.matchMedia('(max-width: 1360px)')
const modal = ref(narrow.matches)
let trigger: HTMLElement | undefined
let inertNodes: HTMLElement[] = []
function syncInert() {
  inertNodes.forEach(node => { node.inert = false })
  inertNodes = []
  if (item.value && modal.value) {
    inertNodes = [...document.querySelectorAll<HTMLElement>('.sidebar, .topbar'), content.value!]
    inertNodes.forEach(node => { node.inert = true })
  }
}
function resize() { modal.value = narrow.matches; syncInert() }
async function open(row: HandbookSpecies, event: Event) {
  selected.value = row.key
  trigger = event.currentTarget instanceof HTMLElement ? event.currentTarget : undefined
  await nextTick()
  syncInert()
  closeButton.value?.focus({ preventScroll: true })
}
function close(restore = true) {
  selected.value = null
  syncInert()
  if (restore) trigger?.focus({ preventScroll: true })
}
function keydown(event: KeyboardEvent) {
  if (!item.value) return
  if (event.key === 'Escape') { event.preventDefault(); close() }
  if (modal.value && event.key === 'Tab') {
    event.preventDefault()
    closeButton.value?.focus()
  }
}
const modes: { mode: HandbookMode; label: string }[] = [
  { mode: 'all', label: '全部' },
  { mode: 'collected', label: '已收集' },
  { mode: 'uncollected', label: '未收集' },
]
watch(data, () => {
  limit.value = PAGE_SIZE
  if (selected.value !== null && !item.value) close(false)
})
watch(() => props.active, value => { if (value) void resume(); else { close(false); pause() } }, { flush: 'sync' })
onMounted(() => {
  if (props.active) void resume(); else pause()
  narrow.addEventListener('change', resize); document.addEventListener('keydown', keydown)
})
onUnmounted(() => { narrow.removeEventListener('change', resize); document.removeEventListener('keydown', keydown) })
defineExpose({ load, pause, resume, resetAccount, error })
</script>
<template>
  <div class="workspace split" :class="{ 'detail-collapsed': !item }" data-vue-page>
    <section ref="content" class="content-panel" :aria-busy="loading">
      <div class="panel-toolbar">
        <span id="hb-count" class="count-badge">收录 {{ data?.collected || 0 }} / {{ data?.total || 0 }} 种</span>
        <label class="inline-field">搜索<input id="hb-search" v-model="filters.search" type="text" placeholder="名字 / 图鉴号 / 图鉴 ID"></label>
        <label class="inline-field">系别<select id="hb-type" v-model="filters.type"><option value="">全部系别</option><option v-for="name in data?.type_options" :key="name">{{ name }}</option></select></label>
        <div id="hb-mode" class="segmented" role="group" aria-label="收集状态">
          <button v-for="entry in modes" :key="entry.mode" type="button" :class="{ active: filters.mode === entry.mode }" :aria-pressed="filters.mode === entry.mode" @click="filters.mode = entry.mode">{{ entry.label }}</button>
        </div>
      </div>
      <div class="table-wrap">
        <div v-if="loading && !data" class="empty-hint" role="status"><UiIcon name="clock" />正在加载图鉴…</div>
        <div v-else-if="error" class="empty-hint" role="alert"><UiIcon name="search" />图鉴加载失败：{{ error }}<div class="button-row"><button class="ghost-button" @click="load">重试</button></div></div>
        <template v-else>
          <div id="hb-grid" class="hb-grid">
            <article v-for="row in shown" :key="row.key" class="hb-card" :class="{ uncollected: !row.collected, active: selected === row.key }" role="button" tabindex="0" :aria-label="`查看${row.name}详情`" :aria-pressed="selected === row.key" @click="open(row, $event)" @keydown.enter.prevent.stop="open(row, $event)" @keydown.space.prevent.stop="open(row, $event)">
              <div class="hb-head">
                <span class="hb-key">{{ row.handbook_no || (row.dex_no ? String(row.dex_no) : row.key) }}</span>
                <span class="hb-art"><span aria-hidden="true">{{ (row.name || '?').slice(0, 1) }}</span><img v-if="row.icon_url" :src="row.icon_url" alt="" loading="lazy" @error="($event.target as HTMLImageElement).remove()"></span>
                <div><strong>{{ row.name }}</strong><small>{{ row.stage ? `第 ${row.stage} 阶` : '' }}</small></div>
              </div>
              <div class="hb-meta">
                <span v-for="(name, index) in row.type_names" :key="name" class="type-badge" :style="typeBadgeStyle(row.type_colors[index])">{{ name }}</span>
                <span v-if="!row.type_names.length" class="muted">—</span>
                <span class="hb-sum">六维 {{ row.stat_sum || '—' }}</span>
              </div>
              <span v-if="row.collected" class="hb-badge">拥有 {{ row.owned_count }} · Lv{{ row.best_level }}</span>
              <span v-else class="hb-badge none">未收集</span>
              <div v-if="row.evolutions.length" class="hb-evo">进化 → <b>{{ row.evolutions[0]!.name }}</b>{{ row.evolutions.length > 1 ? ` 等 ${row.evolutions.length} 条` : '' }}</div>
            </article>
            <div v-if="remaining" class="hb-more"><button id="hb-more-btn" class="ghost-button small" @click="more">显示更多（剩余 {{ remaining }} 种）</button></div>
          </div>
          <div v-if="data && !data.species.length" id="hb-empty" class="empty-hint">没有符合筛选条件的物种<div v-if="filters.search || filters.type || filters.mode !== 'all'" class="button-row"><button class="ghost-button" @click="clear">清除筛选</button></div></div>
        </template>
      </div>
    </section>
    <div v-if="item && modal" class="detail-backdrop" @click="close()"></div>
    <aside v-if="item" id="hb-detail" class="detail-panel detail-open" :role="modal ? 'dialog' : 'region'" :aria-modal="modal || undefined" :aria-label="`${item.name}详情`">
      <button ref="closeButton" type="button" class="ghost-button small detail-close" @click="close()"><UiIcon name="x" />关闭详情</button>
      <HandbookDetail :item="item" />
    </aside>
  </div>
</template>
