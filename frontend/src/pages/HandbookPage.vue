<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import type { ApiClient } from '../api/client'
import { useHandbook } from '../composables/useHandbook'
import { parseHandbook, type HandbookSpecies } from '../types/handbook'
import HandbookDetail from '../components/HandbookDetail.vue'
import PageInspector from '../components/PageInspector.vue'
import PageShell from '../components/PageShell.vue'
import PagePager from '../components/PagePager.vue'
import { useDexDisplay } from '../composables/useDexDisplay'
import DexPortrait from '../components/DexPortrait.vue'
import DexTypeBadge from '../components/DexTypeBadge.vue'
import DexFilterMenu from '../components/DexFilterMenu.vue'
import UiIcon from '../components/UiIcon.vue'
import UiSearch from '../components/UiSearch.vue'
import './catalog-wiki.css'

const props = defineProps<{ api: ApiClient; active: boolean }>()
const { filters, data, loading, error, load, pause, resume, resetAccount, clear } = useHandbook(props.api)
const { view, density } = useDexDisplay()
const page = ref(1), groups = ref<string[]>([])
const groupMode = ref<'union' | 'intersection'>('union')
const filtered = computed(() => (data.value?.species || []).filter(row => !groups.value.length
  || groups.value[groupMode.value === 'intersection' ? 'every' : 'some'](group => row.egg_groups.includes(group))))
const pageSize = 30
const pages = computed(() => Math.max(1, Math.ceil(filtered.value.length / pageSize)))
const shown = computed(() => filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize))
const typeOptions = computed(() => [{ value: '', label: '全部' }, ...(data.value?.type_options || []).filter(Boolean).map(value => ({ value, label: value, iconUrl: data.value?.type_option_icons?.[value] }))])
const groupOptions = computed(() => [{ value: '', label: '全部' }, ...(data.value?.egg_group_options || []).map(value => ({ value, label: displayGroup(value) }))])
const item = ref<HandbookSpecies>()
function displayGroup(group: string) { return group === '未发现' ? '蛋组未知' : group }
const detailLoading = ref(false), detailError = ref('')
const detailTarget = ref<string>()
let detailRequest: AbortController | undefined
let loadedDetailKey: string | undefined
let pendingKey: string | undefined
const content = ref<HTMLElement>(), inspector = ref<InstanceType<typeof PageInspector> | null>(null)
const narrow = window.matchMedia('(max-width: 960px)'), modal = ref(narrow.matches), mobileDetail = ref(false)
let trigger: HTMLElement | undefined
let inertNodes: HTMLElement[] = []
function syncInert() {
  inertNodes.forEach(node => { node.inert = false }); inertNodes = []
  if (mobileDetail.value && modal.value) {
    inertNodes = [...document.querySelectorAll<HTMLElement>('.sidebar, .topbar'), content.value!]
    inertNodes.forEach(node => { node.inert = true })
  }
}
function resize() { modal.value = narrow.matches; syncInert() }
function cancelDetail() { detailRequest?.abort(); detailRequest = undefined; detailLoading.value = false }
async function fetchDetail(key: string) {
  detailTarget.value = key
  cancelDetail()
  const request = new AbortController(); detailRequest = request
  detailLoading.value = true; detailError.value = ''
  try {
    const result = parseHandbook(await props.api(`/api/handbook?details=1&search=${encodeURIComponent(key)}`, request.signal))
    if (request !== detailRequest) return
    const found = result.species.find(row => row.key === key)
    if (!found) throw new Error('本地目录中没有该条目')
    item.value = found
    loadedDetailKey = key
  } catch (err) {
    if (request === detailRequest) detailError.value = err instanceof Error ? err.message : String(err)
  } finally { if (request === detailRequest) detailLoading.value = false }
}
function select(row: HandbookSpecies) {
  if (item.value?.key !== row.key) {
    loadedDetailKey = undefined
    inspector.value?.body?.scrollTo(0, 0)
    void fetchDetail(row.key)
  } else if (loadedDetailKey !== row.key || detailError.value) void fetchDetail(row.key)
}
async function open(row: HandbookSpecies, event: Event) {
  pendingKey = undefined
  select(row)
  trigger = event.currentTarget instanceof HTMLElement ? event.currentTarget : undefined
  mobileDetail.value = true
  await nextTick(); syncInert()
  if (modal.value) inspector.value?.focusClose()
}
function close(restore = true) {
  mobileDetail.value = false; cancelDetail(); syncInert()
  if (restore) trigger?.focus({ preventScroll: true })
}
function goPage(value: number) {
  page.value = Math.max(1, Math.min(pages.value, value || 1))
  const first = shown.value[0]; if (first) select(first)
}
async function resetFilters() {
  groups.value = []; page.value = 1
  await clear()
  if (props.active && filtered.value[0]) select(filtered.value[0])
}
async function reveal(key: string | number) {
  pendingKey = String(key); groups.value = []; page.value = 1
  void clear()
  mobileDetail.value = true
  await fetchDetail(String(key))
  if (!props.active || item.value?.key !== String(key)) return
  await nextTick(); syncInert()
  inspector.value?.body?.scrollTo(0, 0)
  if (modal.value) inspector.value?.focusClose()
}
function filterGroup(group: string) { groups.value = [group]; page.value = 1 }
function keydown(event: KeyboardEvent) {
  if (!mobileDetail.value || !modal.value) return
  if (event.key === 'Escape') { event.preventDefault(); close() }
  if (event.key === 'Tab') {
    const controls = [...(inspector.value?.el?.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input, select, summary, [tabindex="0"]') || [])].filter(node => node.getClientRects().length)
    const first = controls[0], last = controls[controls.length - 1]
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
  }
}
watch(filtered, rows => {
  if (pendingKey) {
    const index = rows.findIndex(row => row.key === pendingKey)
    if (index >= 0) { page.value = Math.floor(index / pageSize) + 1; pendingKey = undefined; return }
  }
  page.value = 1
  if (!rows.some(row => row.key === item.value?.key)) {
    if (rows[0]) select(rows[0]); else { item.value = undefined; cancelDetail() }
  }
})
watch(() => props.active, value => { if (value) void resume(); else { close(false); pause() } }, { flush: 'sync' })
onMounted(() => { if (props.active) void resume(); else pause(); narrow.addEventListener('change', resize); document.addEventListener('keydown', keydown) })
onUnmounted(() => { close(false); narrow.removeEventListener('change', resize); document.removeEventListener('keydown', keydown) })
defineExpose({ load, pause, resume, resetAccount, reveal, error })
</script>
<template>
  <PageShell class="catalog-dex" data-vue-page :busy="loading">
    <template #toolbar>
      <div class="dex-toolbar-heading">
        <nav class="dex-view-switch" aria-label="图鉴分类"><button type="button" class="active" data-goto-page="handbook" aria-current="page">精灵图鉴</button><button type="button" data-goto-page="egg-dex">精灵蛋图鉴</button></nav>
        <p id="hb-count" class="ui-page-meta">资料条目 {{ data?.total || 0 }} 只 · {{ filtered.length === data?.total ? '浏览完整资料库' : `找到 ${filtered.length} 个结果` }}</p>
      </div>
      <div class="dex-toolbar-actions">
        <UiSearch id="hb-search" v-model="filters.search" label="搜索精灵图鉴" placeholder="搜索精灵名称、形态或编号" />
        <DexFilterMenu label="属性" :options="typeOptions" :model-value="filters.type ? [filters.type] : []" :active="active" @update:model-value="filters.type = $event[0] || ''" />
        <DexFilterMenu v-model="groups" v-model:mode="groupMode" label="蛋组" :options="groupOptions" multiple :active="active" />
        <label class="ui-density"><span class="sr-only">卡片密度</span><select v-model="density" aria-label="卡片密度"><option value="comfortable">舒适</option><option value="compact">紧凑</option></select></label>
        <div class="ui-view-switch" role="group" aria-label="卡片视图">
          <button type="button" :aria-pressed="view === 'grid'" title="网格视图" @click="view = 'grid'"><UiIcon name="layout-grid" /></button>
          <button type="button" :aria-pressed="view === 'list'" title="列表视图" @click="view = 'list'"><UiIcon name="table" /></button>
        </div>
      </div>
    </template>
    <div class="dex-browser-layout">
      <section ref="content" class="dex-results" :aria-busy="loading">
        <div v-if="loading && !data" class="empty-hint" role="status">正在加载图鉴…</div>
        <div v-if="error" class="dex-error" role="alert">图鉴加载失败：{{ error }}<button class="ghost-button small" @click="load">重试</button></div>
        <PagePager :page="page" :pages="pages" :page-size="pageSize" unit="只" label="精灵图鉴页码" @update:page="goPage" />
        <div id="hb-grid" class="dex-browser-grid" :class="{ 'is-list': view === 'list', 'is-compact': density === 'compact' }">
          <button v-for="row in shown" :key="row.key" class="dex-browser-card" :class="{ selected: item?.key === row.key }" :aria-label="`查看${row.display_name || row.name}详情`" :aria-pressed="item?.key === row.key" @click="open(row, $event)">
            <span class="dex-card-number">No.{{ row.handbook_no || row.dex_no || '—' }} · {{ row.stage ? `第${row.stage}阶` : '阶段未知' }}</span>
            <DexPortrait :src="row.icon_url || row.artwork_url" :name="row.display_name || row.name" eager /><b>{{ row.display_name || row.name }}</b>
            <div class="dex-card-types"><DexTypeBadge v-for="(name, index) in row.type_names" :key="name" :name="name" :color="row.type_colors[index]" :icon-url="row.type_icons?.[name]" compact /></div>
            <div class="dex-card-groups"><span v-for="group in row.egg_groups" :key="group" class="dex-tag">{{ displayGroup(group) }}</span><small v-if="!row.egg_groups.length">暂无蛋组</small></div>
            <div class="dex-card-summary" aria-label="基础资料"><span><small>种族值</small><b>{{ row.stat_sum > 0 ? row.stat_sum : '—' }}</b></span><span><small>异色</small><b>{{ row.has_shiny ? '可用' : '无' }}</b></span></div>
          </button>
          <div v-if="data && !filtered.length" class="dex-empty"><b>没有找到匹配结果</b><span>试试其他名称，或清除筛选条件。</span><button class="ghost-button" @click="resetFilters">清除筛选</button></div>
        </div>
      </section>
      <div v-if="modal && mobileDetail" class="detail-backdrop" @click="close()"></div>
      <PageInspector v-if="!modal || mobileDetail" ref="inspector" title="精灵详情" :meta="item ? `#${item.handbook_no || item.dex_no || '—'}` : undefined" :modal="modal && mobileDetail" storage-key="handbook" :default-width="360" :aria-busy="detailLoading || undefined" @close="close()">
        <div v-if="detailLoading && !item" class="dex-detail-status" role="status">正在加载资料…</div>
        <div v-if="detailError" class="dex-error" role="alert">{{ detailError }}<button v-if="detailTarget" class="ghost-button small" @click="fetchDetail(detailTarget)">重试</button></div>
        <HandbookDetail v-if="item" :item="item" @navigate="reveal" @filter-group="filterGroup" />
        <div v-else class="dex-empty">选择精灵查看详细资料</div>
      </PageInspector>
    </div>
  </PageShell>
</template>
