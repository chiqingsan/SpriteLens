<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import type { ApiClient } from '../api/client'
import { useHandbook } from '../composables/useHandbook'
import { parseHandbook, type HandbookSpecies } from '../types/handbook'
import HandbookDetail from '../components/HandbookDetail.vue'
import DexPortrait from '../components/DexPortrait.vue'
import DexTypeBadge from '../components/DexTypeBadge.vue'
import DexFilterMenu from '../components/DexFilterMenu.vue'
import UiIcon from '../components/UiIcon.vue'
import './catalog-wiki.css'

const props = defineProps<{ api: ApiClient; active: boolean }>()
const { filters, data, loading, error, load, pause, resume, resetAccount, clear } = useHandbook(props.api)
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
const content = ref<HTMLElement>(), pageStrip = ref<HTMLElement>(), inspector = ref<HTMLElement>(), closeButton = ref<HTMLButtonElement>()
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
    inspector.value?.scrollTo(0, 0)
    void fetchDetail(row.key)
  } else if (loadedDetailKey !== row.key || detailError.value) void fetchDetail(row.key)
}
async function open(row: HandbookSpecies, event: Event) {
  pendingKey = undefined
  select(row)
  trigger = event.currentTarget instanceof HTMLElement ? event.currentTarget : undefined
  mobileDetail.value = true
  await nextTick(); syncInert()
  if (modal.value) closeButton.value?.focus({ preventScroll: true })
}
function close(restore = true) {
  mobileDetail.value = false; cancelDetail(); syncInert()
  if (restore) trigger?.focus({ preventScroll: true })
}
function goPage(value: number) {
  page.value = Math.max(1, Math.min(pages.value, value || 1))
  const first = shown.value[0]; if (first) select(first)
}
function wheelPages(event: WheelEvent) {
  const node = pageStrip.value
  if (!node || node.scrollWidth <= node.clientWidth) return
  event.preventDefault(); node.scrollLeft += event.deltaY || event.deltaX
}
function movePages(direction: number) { pageStrip.value!.scrollLeft += direction * pageStrip.value!.clientWidth * .75 }
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
  inspector.value?.scrollTo(0, 0)
  if (modal.value) closeButton.value?.focus({ preventScroll: true })
}
function filterGroup(group: string) { groups.value = [group]; page.value = 1 }
function keydown(event: KeyboardEvent) {
  if (!mobileDetail.value || !modal.value) return
  if (event.key === 'Escape') { event.preventDefault(); close() }
  if (event.key === 'Tab') {
    const controls = [...(inspector.value?.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input, select, summary, [tabindex="0"]') || [])].filter(node => node.getClientRects().length)
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
watch(() => page.value, async () => {
  await nextTick()
  const node = pageStrip.value?.querySelector<HTMLElement>('.active')
  if (!node || !pageStrip.value) return
  if (node.offsetLeft < pageStrip.value.scrollLeft) pageStrip.value.scrollLeft = node.offsetLeft
  else if (node.offsetLeft + node.offsetWidth > pageStrip.value.scrollLeft + pageStrip.value.clientWidth) {
    pageStrip.value.scrollLeft = node.offsetLeft + node.offsetWidth - pageStrip.value.clientWidth
  }
})
onMounted(() => { if (props.active) void resume(); else pause(); narrow.addEventListener('change', resize); document.addEventListener('keydown', keydown) })
onUnmounted(() => { close(false); narrow.removeEventListener('change', resize); document.removeEventListener('keydown', keydown) })
defineExpose({ load, pause, resume, resetAccount, reveal, error })
</script>
<template>
  <div class="catalog-dex" data-vue-page>
    <header class="dex-toolbar"><div class="dex-toolbar-heading"><nav class="dex-view-switch" aria-label="图鉴分类"><button type="button" class="active" data-goto-page="handbook" aria-current="page">精灵图鉴</button><button type="button" data-goto-page="egg-dex">精灵蛋图鉴</button></nav><h2>精灵图鉴</h2><p id="hb-count">资料条目 {{ data?.total || 0 }} 只 · {{ filtered.length === data?.total ? '浏览完整资料库' : `找到 ${filtered.length} 个结果` }}</p></div>
      <div class="dex-toolbar-actions"><input id="hb-search" v-model="filters.search" type="search" placeholder="搜索精灵名称、形态或编号" aria-label="搜索精灵图鉴">
        <DexFilterMenu label="属性" :options="typeOptions" :model-value="filters.type ? [filters.type] : []" :active="active" @update:model-value="filters.type = $event[0] || ''" />
        <DexFilterMenu v-model="groups" v-model:mode="groupMode" label="蛋组" :options="groupOptions" multiple :active="active" />
      </div>
    </header>
    <div class="dex-browser-layout">
      <section ref="content" class="dex-results" :aria-busy="loading">
        <div v-if="loading && !data" class="empty-hint" role="status">正在加载图鉴…</div>
        <div v-if="error" class="dex-error" role="alert">图鉴加载失败：{{ error }}<button class="ghost-button small" @click="load">重试</button></div>
        <nav class="dex-page-navigation" aria-label="精灵图鉴页码">
          <div class="box-navigation-row">
            <button class="box-scroll" aria-label="向前滚动页码" :disabled="pages < 2" @click="movePages(-1)"><UiIcon name="chevron-left" /></button>
            <div ref="pageStrip" class="page-tab-strip" @wheel="wheelPages">
              <button v-for="number in pages" :key="number" class="box-number" :class="{ active: page === number }" :aria-pressed="page === number" :title="`第 ${number} 页`" @click="goPage(number)">{{ number }}</button>
            </div>
            <button class="box-scroll" aria-label="向后滚动页码" :disabled="pages < 2" @click="movePages(1)"><UiIcon name="chevron-right" /></button>
            <span class="box-total">第 {{ page }} / {{ pages }} 页 · 每页 {{ pageSize }} 只</span>
          </div>
        </nav>
        <div id="hb-grid" class="dex-browser-grid">
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
      <aside ref="inspector" id="hb-detail" class="dex-inspector" :class="{ 'drawer-open': mobileDetail }" :role="modal && mobileDetail ? 'dialog' : 'region'" :aria-modal="modal && mobileDetail || undefined" :aria-busy="detailLoading || undefined" aria-label="精灵详情">
        <button ref="closeButton" class="ghost-button small dex-mobile-close" @click="close()">关闭详情</button>
        <div v-if="detailLoading && !item" class="dex-detail-status" role="status">正在加载资料…</div>
        <div v-if="detailError" class="dex-error" role="alert">{{ detailError }}<button v-if="detailTarget" class="ghost-button small" @click="fetchDetail(detailTarget)">重试</button></div>
        <HandbookDetail v-if="item" :item="item" @navigate="reveal" @filter-group="filterGroup" />
        <div v-else class="dex-empty">选择精灵查看详细资料</div>
      </aside>
    </div>
  </div>
</template>
