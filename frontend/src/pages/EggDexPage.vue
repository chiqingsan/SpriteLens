<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import type { ApiClient } from '../api/client'
import { useEggDex } from '../composables/useEggDex'
import { parseEggDex, type Egg } from '../types/eggDex'
import EggDetail from '../components/EggDetail.vue'
import PageInspector from '../components/PageInspector.vue'
import PageShell from '../components/PageShell.vue'
import PagePager from '../components/PagePager.vue'
import DexPortrait from '../components/DexPortrait.vue'
import DexTypeBadge from '../components/DexTypeBadge.vue'
import DexFilterMenu from '../components/DexFilterMenu.vue'
import UiIcon from '../components/UiIcon.vue'
import UiSearch from '../components/UiSearch.vue'
import UiSegmented from '../components/UiSegmented.vue'
import './catalog-wiki.css'

const props = defineProps<{ api: ApiClient; active: boolean }>()
const { filters, data, loading, error, load, pause, resume, clear } = useEggDex(props.api)
const page = ref(1), groups = ref<string[]>([])
const groupMode = ref<'union' | 'intersection'>('union')
const sort = ref(''), groupCount = ref(''), sameRide = ref('')
const filtered = computed(() => {
  const rows = (data.value?.eggs || []).filter(row => (!groups.value.length
    || groups.value[groupMode.value === 'intersection' ? 'every' : 'some'](group => row.egg_group_names.includes(group)))
    && (!groupCount.value || row.egg_group_names.filter(group => !['无', '未发现', '无法孵蛋'].includes(group)).length === 2)
    && (!sameRide.value || row.can_same_ride === (sameRide.value === 'yes')))
  if (sort.value) rows.sort((a, b) => {
    const knownA = a.hatch_seconds > 0, knownB = b.hatch_seconds > 0
    if (knownA !== knownB) return knownA ? -1 : 1
    return (knownA ? (sort.value === 'asc' ? 1 : -1) * (a.hatch_seconds - b.hatch_seconds) : 0)
      || a.handbook_no.localeCompare(b.handbook_no) || a.egg_conf_id - b.egg_conf_id
  })
  return rows
})
const pageSize = 30
const pages = computed(() => Math.max(1, Math.ceil(filtered.value.length / pageSize)))
const shown = computed(() => filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize))
const typeOptions = computed(() => [{ value: '', label: '全部' }, ...(data.value?.egg_types || []).map(value => ({ value, label: value, iconUrl: data.value?.type_option_icons?.[value] }))])
const groupOptions = computed(() => [{ value: '', label: '全部' }, ...(data.value?.groups || []).map(value => ({ value, label: displayGroup(value) }))])
const item = ref<Egg>()
function displayGroup(group: string) { return group === '未发现' ? '蛋组未知' : group }
const detailLoading = ref(false), detailError = ref('')
const detailTarget = ref<string>()
let detailRequest: AbortController | undefined
let loadedDetailKey: string | undefined
let pendingKey: string | undefined
const content = ref<HTMLElement>(), inspector = ref<InstanceType<typeof PageInspector> | null>(null), moreFilters = ref<HTMLDialogElement>(), moreFiltersButton = ref<HTMLButtonElement>()
const narrow = window.matchMedia('(max-width: 960px)'), modal = ref(narrow.matches), mobileDetail = ref(false)
const moreFiltersOpen = ref(false)
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
    const result = parseEggDex(await props.api(`/api/eggs?details=1&search=${encodeURIComponent(key)}`, request.signal))
    if (request !== detailRequest) return
    const found = result.eggs.find(row => String(row.egg_conf_id) === key)
    if (!found) throw new Error('本地目录中没有该条目')
    item.value = found
    loadedDetailKey = key
  } catch (err) {
    if (request === detailRequest) detailError.value = err instanceof Error ? err.message : String(err)
  } finally { if (request === detailRequest) detailLoading.value = false }
}
function select(row: Egg) {
  if (item.value?.egg_conf_id !== row.egg_conf_id) {
    loadedDetailKey = undefined
    inspector.value?.body?.scrollTo(0, 0)
    void fetchDetail(String(row.egg_conf_id))
  } else if (loadedDetailKey !== String(row.egg_conf_id) || detailError.value) void fetchDetail(String(row.egg_conf_id))
}
async function open(row: Egg, event: Event) {
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
const moreFiltersActive = computed(() => Boolean(sort.value || groupCount.value || sameRide.value))
const moreFiltersSummary = computed(() => moreFiltersActive.value ? '已设置' : '全部')
function openMoreFilters() { moreFilters.value?.showModal(); moreFiltersOpen.value = true }
function closeMoreFilters(restore = true) {
  if (moreFilters.value?.open) moreFilters.value.close()
  moreFiltersOpen.value = false
  if (restore) moreFiltersButton.value?.focus({ preventScroll: true })
}
async function resetFilters() {
  groups.value = []; sort.value = ''; groupCount.value = ''; sameRide.value = ''; page.value = 1
  await clear()
  if (props.active && filtered.value[0]) select(filtered.value[0])
}
async function reveal(key: string | number) {
  pendingKey = String(key); groups.value = []; sort.value = ''; groupCount.value = ''; sameRide.value = ''; page.value = 1
  void clear()
  mobileDetail.value = true
  await fetchDetail(String(key))
  if (!props.active || String(item.value?.egg_conf_id) !== String(key)) return
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
    const index = rows.findIndex(row => String(row.egg_conf_id) === pendingKey)
    if (index >= 0) { page.value = Math.floor(index / pageSize) + 1; pendingKey = undefined; return }
  }
  page.value = 1
  if (!rows.some(row => row.egg_conf_id === item.value?.egg_conf_id)) {
    if (rows[0]) select(rows[0]); else { item.value = undefined; cancelDetail() }
  }
})
watch(() => props.active, value => { if (value) void resume(); else { close(false); closeMoreFilters(false); pause() } }, { flush: 'sync' })
onMounted(() => { if (props.active) void resume(); else pause(); narrow.addEventListener('change', resize); document.addEventListener('keydown', keydown) })
onUnmounted(() => { close(false); closeMoreFilters(false); narrow.removeEventListener('change', resize); document.removeEventListener('keydown', keydown) })
defineExpose({ load, pause, resume, reveal, error })
</script>
<template>
  <PageShell class="catalog-dex" data-vue-page :busy="loading">
    <template #toolbar>
      <div class="dex-toolbar-heading">
        <UiSegmented navigation class="dex-view-switch" role="navigation" aria-label="图鉴分类"><button type="button" data-goto-page="handbook">精灵图鉴</button><button type="button" class="active" data-goto-page="egg-dex" aria-current="page">精灵蛋图鉴</button></UiSegmented>
        <p id="ed-count" class="ui-page-meta">资料条目 {{ data?.total || 0 }} 种 · {{ filtered.length === data?.total ? '浏览完整资料库' : `找到 ${filtered.length} 个结果` }}</p>
      </div>
      <div class="dex-toolbar-actions">
        <UiSearch id="ed-search" v-model="filters.search" label="搜索蛋蛋图鉴" placeholder="搜索蛋名、精灵或编号" />
        <DexFilterMenu label="蛋类型" :options="typeOptions" :model-value="filters.egg_type ? [filters.egg_type] : []" :active="active" @update:model-value="filters.egg_type = $event[0] || ''" />
        <DexFilterMenu v-model="groups" v-model:mode="groupMode" label="蛋组" :options="groupOptions" multiple :active="active" />
        <button ref="moreFiltersButton" class="dex-filter-button dex-more-filter-trigger" :class="{ active: moreFiltersActive }" type="button" aria-haspopup="dialog" :aria-expanded="moreFiltersOpen" @click="openMoreFilters"><small>更多筛选</small><b>{{ moreFiltersSummary }}</b><UiIcon name="adjustments" /></button>
      </div>
    </template>
    <dialog ref="moreFilters" class="dex-filter-dialog dex-more-filter-dialog" aria-labelledby="ed-more-filters-title" @click.self="closeMoreFilters()" @close="moreFiltersOpen = false">
      <header><div class="dex-dialog-heading"><h3 id="ed-more-filters-title">更多筛选</h3></div><button class="ghost-button small" type="button" aria-label="关闭更多筛选" @click="closeMoreFilters()"><UiIcon name="x" /></button></header>
      <p>选择后立即更新图鉴结果</p>
      <section class="dex-more-filter-section"><h4>排序</h4><div class="dex-more-filter-options"><button v-for="option in [{ value: '', label: '默认排序' }, { value: 'asc', label: '孵化时间升序' }, { value: 'desc', label: '孵化时间降序' }]" :key="option.value" type="button" :aria-pressed="sort === option.value" @click="sort = option.value"><span>{{ option.label }}</span><UiIcon name="circle-check" :class="{ 'is-hidden': sort !== option.value }" /></button></div></section>
      <section class="dex-more-filter-section"><h4>组别</h4><div class="dex-more-filter-options"><button v-for="option in [{ value: '', label: '全部' }, { value: 'dual', label: '只看双组别' }]" :key="option.value" type="button" :aria-pressed="groupCount === option.value" @click="groupCount = option.value"><span>{{ option.label }}</span><UiIcon name="circle-check" :class="{ 'is-hidden': groupCount !== option.value }" /></button></div></section>
      <section class="dex-more-filter-section"><h4>同乘</h4><div class="dex-more-filter-options"><button v-for="option in [{ value: '', label: '全部' }, { value: 'yes', label: '可同乘' }, { value: 'no', label: '不可同乘' }]" :key="option.value" type="button" :aria-pressed="sameRide === option.value" @click="sameRide = option.value"><span>{{ option.label }}</span><UiIcon name="circle-check" :class="{ 'is-hidden': sameRide !== option.value }" /></button></div></section>
    </dialog>
    <div class="dex-browser-layout">
      <section ref="content" class="dex-results" :aria-busy="loading">
        <div v-if="loading && !data" class="empty-hint" role="status">正在加载蛋图鉴…</div>
        <div v-if="error" class="dex-error" role="alert">蛋图鉴加载失败：{{ error }}<button class="ghost-button small" @click="load">重试</button></div>
        <PagePager :page="page" :pages="pages" :page-size="pageSize" unit="枚" label="蛋蛋图鉴页码" @update:page="goPage" />
        <div id="ed-grid" class="dex-browser-grid">
          <button v-for="row in shown" :key="row.egg_conf_id" class="dex-browser-card egg" :class="{ selected: item?.egg_conf_id === row.egg_conf_id }" :aria-label="`查看${row.egg_name}详情`" :aria-pressed="item?.egg_conf_id === row.egg_conf_id" @click="open(row, $event)">
            <span class="dex-card-number">No.{{ row.handbook_no || '—' }} · {{ row.egg_type_name || '类型未知' }}</span><DexPortrait :src="row.egg_icon_url" :name="row.egg_name" eager /><b>{{ row.egg_name }}</b>
            <div class="dex-card-types"><DexTypeBadge v-for="(name, index) in (row.type_names || [])" :key="name" :name="name" :color="row.type_colors?.[index]" :icon-url="row.type_icons?.[name]" compact /></div>
            <div class="dex-card-groups"><span v-for="group in row.egg_group_names" :key="group" class="dex-tag">{{ displayGroup(group) }}</span><small v-if="!row.egg_group_names.length">暂无蛋组</small></div>
          </button>
          <div v-if="data && !filtered.length" class="dex-empty"><b>没有找到匹配结果</b><span>试试其他名称，或清除筛选条件。</span><button class="ghost-button" @click="resetFilters">清除筛选</button></div>
        </div>
      </section>
      <div v-if="modal && mobileDetail" class="detail-backdrop" @click="close()"></div>
      <PageInspector v-if="!modal || mobileDetail" ref="inspector" title="精灵蛋详情" :meta="item ? `#${item.egg_conf_id}` : undefined" :modal="modal && mobileDetail" storage-key="egg-dex" :default-width="360" :aria-busy="detailLoading || undefined" @close="close()">
        <div v-if="detailLoading && !item" class="dex-detail-status" role="status">正在加载资料…</div>
        <div v-if="detailError" class="dex-error" role="alert">{{ detailError }}<button v-if="detailTarget" class="ghost-button small" @click="fetchDetail(detailTarget)">重试</button></div>
        <EggDetail v-if="item" :key="item.egg_conf_id" :egg="item" @filter-group="filterGroup" /><div v-else class="dex-empty">选择精灵蛋查看详细资料</div>
      </PageInspector>
    </div>
  </PageShell>
</template>
