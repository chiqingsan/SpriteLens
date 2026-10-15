<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch, type ComponentPublicInstance } from 'vue'
import { useVirtualizer } from '@tanstack/vue-virtual'
import type { EggBoxHost } from '../composables/useEggBox'
import { useEggBox } from '../composables/useEggBox'
import EggBoxCard from '../components/EggBoxCard.vue'
import EggBoxDetail from '../components/EggBoxDetail.vue'
import UiIcon from '../components/UiIcon.vue'
import './egg-box.css'

const props = defineProps<{ host: EggBoxHost }>()
const model = useEggBox(props.host)
const narrow = window.matchMedia('(max-width: 960px)')
const isNarrow = ref(narrow.matches)
const mobileDetailOpen = ref(false)
const detailRef = ref<InstanceType<typeof EggBoxDetail> | null>(null)
const listViewport = ref<HTMLElement | null>(null)
const columnCount = ref(5)
const eggRows = computed(() => {
  const eggs = model.visibleEggs.value
  const rows: (typeof eggs)[] = []
  for (let index = 0; index < eggs.length; index += columnCount.value) {
    rows.push(eggs.slice(index, index + columnCount.value))
  }
  return rows
})
const rowVirtualizerOptions = computed(() => ({
  count: eggRows.value.length,
  getScrollElement: () => listViewport.value,
  estimateSize: () => 260,
  getItemKey: (index: number) => eggRows.value[index]?.[0]?.instance_id ?? index,
  overscan: 2,
}))
const rowVirtualizer = useVirtualizer(rowVirtualizerOptions)
const virtualRows = computed(() => rowVirtualizer.value.getVirtualItems())
const virtualHeight = computed(() => rowVirtualizer.value.getTotalSize())
const position = computed(() => model.visibleEggs.value.findIndex(egg => egg.instance_id === model.selectedId.value) + 1)
let trigger: HTMLElement | undefined
let inertNodes: HTMLElement[] = []
let columnObserver: ResizeObserver
const summary = computed(() => {
  const data = model.data.value
  if (!data || data.source === 'unknown') return '蛋仓状态未知 · 完整性未确认'
  const source = data.source === 'historical' ? '历史缓存' : data.source === 'mixed' ? '观察与历史' : '已观察'
  return `${source} ${data.total} 枚（完整性未确认）`
})
const emptyMessage = computed(() => {
  if (model.error.value) return ''
  if (model.filters.search || model.filters.category !== 'all') return '没有符合条件的蛋'
  return model.data.value?.source === 'unknown'
    ? '尚未观察到蛋仓数据。开始采集后，进入游戏并打开蛋仓即可积累记录。'
    : '当前观察或缓存中没有蛋，不能据此确认游戏蛋仓为空。'
})
watch(model.visibleEggs, async () => {
  if (listViewport.value) listViewport.value.scrollTop = 0
  await nextTick()
  syncColumnCount()
  rowVirtualizer.value.measure()
})

function syncColumnCount() {
  const grid = listViewport.value?.querySelector<HTMLElement>('.eggbox-grid')
  if (!grid) return
  const count = getComputedStyle(grid).gridTemplateColumns.trim().split(/\s+/).length
  if (count !== columnCount.value) {
    columnCount.value = count
    void nextTick(() => rowVirtualizer.value.measure())
  }
}

function measureRow(element: Element | ComponentPublicInstance | null) {
  if (element instanceof HTMLElement) rowVirtualizer.value.measureElement(element)
}

function syncInert() {
  inertNodes.forEach(node => { node.inert = false })
  inertNodes = []
  if (isNarrow.value && mobileDetailOpen.value) {
    inertNodes = [...document.querySelectorAll<HTMLElement>('.sidebar, .topbar')]
    const list = document.querySelector<HTMLElement>('.eggbox-list-panel')
    if (list) inertNodes.push(list)
    inertNodes.forEach(node => { node.inert = true })
  }
}
async function open(egg: NonNullable<typeof model.selected.value>, event: MouseEvent) {
  model.select(egg)
  trigger = event.currentTarget instanceof HTMLElement ? event.currentTarget : undefined
  mobileDetailOpen.value = isNarrow.value
  await nextTick()
  syncInert()
  if (mobileDetailOpen.value) detailRef.value?.focusClose()
}
function onResize() {
  isNarrow.value = narrow.matches
  mobileDetailOpen.value = false
  syncInert()
  void nextTick(() => trigger?.focus({ preventScroll: true }))
}
async function closeMobileDetail() {
  mobileDetailOpen.value = false
  if (isNarrow.value) model.clearSelection()
  syncInert()
  await nextTick()
  if (trigger?.isConnected) trigger.focus({ preventScroll: true })
}
function changeCategory(category: string) {
  model.filters.category = category
}
async function moveSelection(offset: number) {
  model.moveSelection(offset)
  if (!isNarrow.value) {
    const selectedIndex = model.visibleEggs.value.findIndex(egg => egg.instance_id === model.selectedId.value)
    const rowIndex = Math.floor(selectedIndex / columnCount.value)
    rowVirtualizer.value.scrollToIndex(rowIndex, { align: 'auto' })
    await nextTick()
    document.querySelector<HTMLElement>(`[data-egg-instance="${model.selectedId.value}"]`)?.scrollIntoView({ block: 'nearest' })
  }
}
function pause() {
  mobileDetailOpen.value = false
  syncInert()
  model.pause()
}
function resetAccount() {
  mobileDetailOpen.value = false
  syncInert()
  model.resetAccount()
}
function keydown(event: KeyboardEvent) {
  if (!isNarrow.value || !mobileDetailOpen.value) return
  if (event.key === 'Escape') {
    event.preventDefault()
    void closeMobileDetail()
    return
  }
  if (event.key !== 'Tab') return
  const focusable = [...document.querySelectorAll<HTMLButtonElement>('.eggbox-detail-panel button:not(:disabled)')]
  if (!focusable.length) return
  const index = focusable.indexOf(document.activeElement as HTMLButtonElement)
  if (event.shiftKey && index <= 0) {
    event.preventDefault()
    focusable.at(-1)?.focus()
  } else if (!event.shiftKey && index === focusable.length - 1) {
    event.preventDefault()
    focusable[0].focus()
  }
}

onMounted(() => {
  columnObserver = new ResizeObserver(syncColumnCount)
  if (listViewport.value) columnObserver.observe(listViewport.value)
  syncColumnCount()
  narrow.addEventListener('change', onResize)
  document.addEventListener('keydown', keydown)
  void model.load()
})
onUnmounted(() => {
  columnObserver.disconnect()
  narrow.removeEventListener('change', onResize)
  document.removeEventListener('keydown', keydown)
  inertNodes.forEach(node => { node.inert = false })
})

defineExpose({
  load: model.load,
  pause,
  resetAccount,
})
</script>

<template>
  <div class="eggbox-page">
    <section class="eggbox-list-panel" :aria-busy="model.loading.value">
      <header class="eggbox-list-toolbar">
        <div class="eggbox-list-summary">
          <span class="count-badge"><UiIcon name="egg" /> {{ summary }}</span>
          <span v-if="model.data.value?.hatching !== null && model.data.value" class="eggbox-hatching-count">在孵 {{ model.data.value.hatching }} 枚</span>
        </div>
        <div class="eggbox-list-controls">
          <button type="button" class="eggbox-sort" :class="model.filters.ascending ? 'eggbox-sort--ascending' : 'eggbox-sort--descending'"
            :aria-pressed="!model.filters.ascending"
            :aria-label="`当前按获得时间${model.filters.ascending ? '升序' : '倒序'}排列，点击切换为${model.filters.ascending ? '倒序' : '升序'}`"
            :title="`当前：${model.filters.ascending ? '升序' : '倒序'}，点击切换`"
            @click="model.filters.ascending = !model.filters.ascending">
            <UiIcon :name="model.filters.ascending ? 'arrow-up' : 'arrow-down'" />
            <span>{{ model.filters.ascending ? '升序' : '倒序' }}</span>
          </button>
          <label class="eggbox-search">
            <UiIcon name="search" />
            <span class="sr-only">搜索蛋</span>
            <input v-model="model.filters.search" type="search" placeholder="搜索蛋名 / 物种 / 编号">
          </label>
        </div>
      </header>

      <nav class="eggbox-categories" aria-label="蛋类型筛选">
        <button v-for="category in model.categories.value" :key="category.id" type="button"
          class="eggbox-category" :class="{ active: model.filters.category === category.id }"
          :aria-pressed="model.filters.category === category.id" @click="changeCategory(category.id)">
          {{ category.label }} <span>{{ category.count }}</span>
        </button>
      </nav>

      <div ref="listViewport" class="eggbox-list-scroll">
        <div v-if="model.loading.value && !model.data.value" class="empty-hint" role="status"><UiIcon name="clock" />正在加载蛋仓…</div>
        <div v-else-if="model.error.value" class="empty-hint" role="alert">
          <UiIcon name="search" />蛋仓加载失败：{{ model.error.value }}
          <div class="button-row"><button type="button" class="ghost-button" @click="model.load">重试</button></div>
        </div>
        <div v-else-if="!model.visibleEggs.value.length" class="empty-hint">
          <UiIcon name="search" />{{ emptyMessage }}
          <div v-if="model.data.value?.eggs.length" class="button-row"><button type="button" class="ghost-button" @click="model.filters.search = ''; model.filters.category = 'all'">清除筛选</button></div>
        </div>
        <div v-else class="eggbox-list-content">
          <div class="eggbox-virtual-space" :style="{ height: `${virtualHeight}px` }">
            <div v-for="row in virtualRows" :key="row.index" :ref="measureRow" class="eggbox-virtual-row"
              :data-index="row.index" :style="{ transform: `translateY(${row.start}px)` }">
              <div class="eggbox-grid">
                <EggBoxCard v-for="egg in eggRows[row.index]" :key="egg.instance_id" :egg="egg"
                  :selected="model.selectedId.value === egg.instance_id" @select="open" />
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <div v-if="isNarrow && mobileDetailOpen" class="eggbox-detail-backdrop" @click="closeMobileDetail"></div>
    <aside v-if="!isNarrow || mobileDetailOpen" class="eggbox-detail-panel"
      :role="isNarrow ? 'dialog' : 'region'" :aria-modal="isNarrow || undefined" aria-label="精灵蛋详情">
      <EggBoxDetail v-if="model.selected.value" ref="detailRef" :egg="model.selected.value" :position="position"
        :total="model.visibleEggs.value.length" @previous="moveSelection(-1)"
        @next="moveSelection(1)" @close="closeMobileDetail" />
      <div v-else class="empty-hint eggbox-detail-empty"><UiIcon name="egg" />选择一枚蛋查看详情</div>
    </aside>
  </div>
</template>
