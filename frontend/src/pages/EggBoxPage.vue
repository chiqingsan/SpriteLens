<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch, type ComponentPublicInstance } from 'vue'
import { useVirtualizer } from '@tanstack/vue-virtual'
import type { EggBoxHost } from '../composables/useEggBox'
import { useEggBox } from '../composables/useEggBox'
import EggBoxCard from '../components/EggBoxCard.vue'
import EggBoxDetail from '../components/EggBoxDetail.vue'
import PageInspector from '../components/PageInspector.vue'
import PageShell from '../components/PageShell.vue'
import UiIcon from '../components/UiIcon.vue'
import UiSearch from '../components/UiSearch.vue'
import UiSelect from '../components/UiSelect.vue'
import type { EggBoxAnnotations, EggBoxEntry } from '../types/eggBox'
import './egg-box.css'

const props = defineProps<{ host: EggBoxHost }>()
const model = useEggBox(props.host)
const narrow = window.matchMedia('(max-width: 960px)')
const isNarrow = ref(narrow.matches)
const mobileDetailOpen = ref(false)
const inspectorRef = ref<InstanceType<typeof PageInspector> | null>(null)
const favoriteBusy = reactive(new Set<string>())
const favoriteError = ref('')
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
  estimateSize: () => 230,
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
let pageGeneration = 0
let pageActive = true
function favoriteKey(uid: number, instanceId: number) { return `${uid}:${instanceId}` }
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
watch(model.visibleEggs, async (eggs, previousEggs) => {
  const orderChanged = eggs.length !== previousEggs.length
    || eggs.some((egg, index) => egg.instance_id !== previousEggs[index]?.instance_id)
  if (!orderChanged) return
  await nextTick()
  syncColumnCount()
  rowVirtualizer.value.measure()
  rowVirtualizer.value.scrollToOffset(0)
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
  if (mobileDetailOpen.value) inspectorRef.value?.focusClose()
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
function updateAnnotations(value: EggBoxAnnotations) {
  const uid = model.data.value?.uid
  const egg = model.selected.value
  if (uid && egg) model.updateAnnotations(uid, egg.instance_id, value)
}
function saveAnnotations() {
  const uid = model.data.value?.uid
  const egg = model.selected.value
  if (uid && egg) model.saveAnnotations(uid, egg.instance_id)
}
async function toggleFavorite(egg: EggBoxEntry) {
  const uid = model.data.value?.uid
  if (!uid) return
  const generation = pageGeneration
  const key = favoriteKey(uid, egg.instance_id)
  if (favoriteBusy.has(key)) return
  favoriteBusy.add(key)
  favoriteError.value = ''
  try {
    await props.host.saveFavorite({ uid, instance_id: egg.instance_id, favorite: !egg.favorite })
    if (!pageActive || generation !== pageGeneration || model.data.value?.uid !== uid) return
    model.setFavorite(egg.instance_id, !egg.favorite)
  } catch (cause) {
    if (pageActive && generation === pageGeneration) {
      favoriteError.value = cause instanceof Error ? cause.message : String(cause)
    }
  } finally {
    favoriteBusy.delete(key)
  }
}
function pause() {
  pageActive = false
  pageGeneration += 1
  mobileDetailOpen.value = false
  syncInert()
  model.pause()
}
function resetAccount() {
  pageActive = false
  pageGeneration += 1
  mobileDetailOpen.value = false
  syncInert()
  model.resetAccount()
}
function load() {
  pageActive = true
  return model.load()
}
function resume(version: number) {
  pageActive = true
  return model.resume(version)
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
  pageActive = true
  columnObserver = new ResizeObserver(syncColumnCount)
  if (listViewport.value) columnObserver.observe(listViewport.value)
  syncColumnCount()
  narrow.addEventListener('change', onResize)
  document.addEventListener('keydown', keydown)
  void load()
})
onUnmounted(() => {
  pageActive = false
  pageGeneration += 1
  columnObserver.disconnect()
  narrow.removeEventListener('change', onResize)
  document.removeEventListener('keydown', keydown)
  inertNodes.forEach(node => { node.inert = false })
})

defineExpose({
  flush: model.flush,
  load,
  resume,
  pause,
  resetAccount,
})
</script>

<template>
  <PageShell class="eggbox-page" :busy="model.loading.value">
    <p v-if="favoriteError" class="eggbox-favorite-error" role="alert">收藏失败：{{ favoriteError }}</p>
    <template #toolbar>
        <div class="eggbox-list-summary">
          <span class="count-badge"><UiIcon name="egg" /> {{ summary }}</span>
          <span v-if="model.data.value?.hatching !== null && model.data.value" class="eggbox-hatching-count">在孵 {{ model.data.value.hatching }} 枚</span>
        </div>
        <div class="eggbox-list-controls">
          <button type="button" class="ghost-button small" data-goto-page="egg-dex" title="到蛋图鉴查蛋的孵化与蛋组信息">蛋图鉴</button>
          <UiSelect :model-value="model.filters.sort" class="eggbox-sort-select" size="sm" label="蛋仓排序"
            @change="model.filters.sort = String($event)"
            :options="[{ value: 'time', label: '时间' }, { value: 'large', label: '大块头' },
              { value: 'small', label: '小不点' }, { value: 'academy', label: '学院窝' },
              { value: 'dex', label: '图鉴 ID' }]" />
          <button type="button" class="eggbox-sort" :class="model.filters.ascending ? 'eggbox-sort--ascending' : 'eggbox-sort--descending'"
            :aria-pressed="!model.filters.ascending"
            :aria-label="`获得时间${model.filters.ascending ? '升序' : '倒序'}，点击切换为${model.filters.ascending ? '倒序' : '升序'}`"
            :title="`获得时间${model.filters.ascending ? '升序' : '倒序'}（同档内），点击切换`"
            @click="model.filters.ascending = !model.filters.ascending">
            <UiIcon :name="model.filters.ascending ? 'arrow-up' : 'arrow-down'" />
            <span>{{ model.filters.ascending ? '时间升序' : '时间倒序' }}</span>
          </button>
          <UiSearch v-model="model.filters.search" class="eggbox-search" compact label="搜索蛋" placeholder="搜索蛋名 / 精灵 / 进化链 / 编号" />
        </div>
    </template>

    <div class="eggbox-body">
      <section class="eggbox-list-panel" :aria-busy="model.loading.value">
        <nav class="eggbox-categories" aria-label="蛋类型筛选">
        <button v-for="category in model.categories.value" :key="category.id" type="button"
          class="eggbox-category" :class="{ active: model.filters.category === category.id }"
          :aria-pressed="model.filters.category === category.id" @click="changeCategory(category.id)">
          {{ category.label }} <span>{{ category.count }}</span>
        </button>
      </nav>

      <div ref="listViewport" class="eggbox-list-scroll" :class="{ 'is-empty': !model.visibleEggs.value.length }">
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
                  :selected="model.selectedId.value === egg.instance_id" :favorite-saving="Boolean(model.data.value && favoriteBusy.has(favoriteKey(model.data.value.uid, egg.instance_id)))"
                  @select="open" @favorite="toggleFavorite" />
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <div v-if="isNarrow && mobileDetailOpen" class="eggbox-detail-backdrop" @click="closeMobileDetail"></div>
    <PageInspector v-if="!isNarrow || mobileDetailOpen" ref="inspectorRef" title="精灵蛋详情"
      :meta="model.selected.value ? `#${model.selected.value.instance_id}` : undefined"
      :modal="isNarrow && mobileDetailOpen" storage-key="egg-box" :default-width="360"
      @close="closeMobileDetail">
      <template #actions>
        <template v-if="model.selected.value">
          <button type="button" class="eggbox-favorite-button eggbox-detail-favorite" :class="{ active: model.selected.value.favorite }"
            :aria-label="model.selected.value.favorite ? '取消收藏' : '收藏这枚蛋'" :aria-pressed="model.selected.value.favorite"
            :disabled="Boolean(model.data.value && favoriteBusy.has(favoriteKey(model.data.value.uid, model.selected.value.instance_id)))"
            @click="toggleFavorite(model.selected.value)"><UiIcon :name="model.selected.value.favorite ? 'star-filled' : 'star'" /></button>
          <button type="button" class="ghost-button small" aria-label="上一枚" :disabled="position <= 1" @click="moveSelection(-1)"><UiIcon name="chevron-left" /></button>
          <button type="button" class="ghost-button small" aria-label="下一枚" :disabled="position >= model.visibleEggs.value.length" @click="moveSelection(1)"><UiIcon name="chevron-right" /></button>
        </template>
      </template>
      <EggBoxDetail v-if="model.selected.value" :egg="model.selected.value" :position="position"
        :total="model.visibleEggs.value.length" :nature-options="model.data.value?.nature_options || []"
        :annotations="model.annotationsFor(model.selected.value)" :annotation-error="model.annotationErrorFor(model.selected.value)"
        :favorite-saving="Boolean(model.data.value && favoriteBusy.has(favoriteKey(model.data.value.uid, model.selected.value.instance_id)))"
        @update-annotations="updateAnnotations" @save-annotations="saveAnnotations" />
      <div v-else class="empty-hint eggbox-detail-empty"><UiIcon name="egg" />选择一枚蛋查看详情</div>
      </PageInspector>
    </div>
  </PageShell>
</template>
