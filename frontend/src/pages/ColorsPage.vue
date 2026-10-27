<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import type { ApiClient } from '../api/client'
import { useColors } from '../composables/useColors'
import { matrixKey, type ColorAxis, type ColorCell, type ColorPet } from '../types/colors'
import ColorCardFace from '../components/ColorCardFace.vue'
import UiIcon from '../components/UiIcon.vue'

type ColorTab = 'owned' | 'catalog'
type CatalogStatusFilter = 'all' | 'owned' | 'unowned' | 'seasonal'
type CellState = 'empty' | 'card' | 'pets'
type MatrixCellView = { state: CellState; key: string; cell: ColorCell | null; owners: ColorPet[] }

const props = defineProps<{ api: ApiClient; active: boolean }>()
const { data, loading, error, load, pause, resume, resetAccount } = useColors(props.api)
const failed = ref(new Set<string>())
const activeTab = ref<ColorTab>('owned')
const selectedKey = ref('')
const catalogFiltersOpen = ref(false)
const catalogStatus = ref<CatalogStatusFilter>('all')
const catalogBase = ref('')
const catalogMix = ref('')
const catalogStatusOptions: Array<{ value: CatalogStatusFilter; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'owned', label: '已持有' },
  { value: 'unowned', label: '未持有' },
  { value: 'seasonal', label: '赛季卡' },
]
const failedKey = (gid: number | string) => String(gid)
function failedIcon(gid: number | string) { failed.value.add(failedKey(gid)) }

const cardOwners = computed(() => {
  const result = new Map<string, ColorPet[]>()
  const colors = data.value
  if (!colors) return result
  const add = (pet: ColorPet) => {
    if (!pet.card_id) return
    const list = result.get(pet.card_id) || []
    if (!list.some(item => String(item.gid) === String(pet.gid))) list.push(pet)
    result.set(pet.card_id, list)
  }
  Object.values(colors.matrix).forEach(pets => pets.forEach(add))
  colors.seasonal.forEach(add)
  return result
})
const ownedCardCount = computed(() => cardOwners.value.size)

const particleIds = computed(() => {
  const result = new Map<string, number>()
  cardOwners.value.forEach((pets, cardId) => {
    const particle = pets.find(pet => pet.color_card?.particle_id !== undefined)?.color_card?.particle_id
    if (particle !== undefined) result.set(cardId, particle)
  })
  return result
})

const catalogCards = computed(() => data.value?.catalogs || [])
const specialAxisCards = computed(() => new Map(catalogCards.value
  .filter(card => /^(1000|s[1-4])$/.test(card.card_id))
  .map(card => [card.mix_name, card.card_id])))
const displayMixName = (name: string) => name === '浅灰' ? '黑白' : name
const filteredCatalogCards = computed(() => catalogCards.value.filter(card => {
  const owners = cardOwners.value.get(card.card_id) || []
  const seasonal = card.card_id.startsWith('s')
  const statusMatches = catalogStatus.value === 'all'
    || (catalogStatus.value === 'owned' && owners.length > 0)
    || (catalogStatus.value === 'unowned' && owners.length === 0)
    || (catalogStatus.value === 'seasonal' && seasonal)
  return statusMatches
    && (!catalogBase.value || card.base_name === catalogBase.value)
    && (!catalogMix.value || card.mix_name === catalogMix.value)
}))

const catalogFilterSummary = computed(() => {
  const filters = [
    catalogStatusOptions.find(option => option.value === catalogStatus.value)?.label || '',
    catalogBase.value,
    displayMixName(catalogMix.value),
  ].filter(Boolean)
  return filters.length === 1 && filters[0] === '全部' ? '全部条件' : filters.join(' · ')
})

const matrixAxis = computed(() => {
  const colors = data.value
  if (!colors) return { base: [] as ColorAxis[], mix: [] as ColorAxis[] }
  const base = [...colors.base_axis]
  const mix = [...colors.mix_axis]
  const seasonal = ['s1', 's2', 's3', 's4']
    .map(cardId => colors.catalogs.find(card => card.card_id.toLowerCase() === cardId))
    .filter((card): card is ColorCell => !!card)
  if (seasonal.length) {
    base.push({ name: '赛季', hex: '', letter: '' })
    seasonal.forEach(card => {
      mix.push({ name: card.mix_name || card.card_id.toUpperCase(), hex: card.mix_color, letter: '' })
    })
  }
  return { base, mix }
})

function cardFor(baseName: string, mixName: string): ColorCell | null {
  const colors = data.value
  if (!colors) return null
  const key = matrixKey(baseName, mixName)
  if (activeTab.value === 'owned') {
    if (colors.matrix[key]?.length) return colors.cells[key] || null
    if (baseName !== '赛季') return null
    const seasonal = colors.catalogs.find(card => card.base_name === baseName && card.mix_name === mixName)
    return seasonal && (cardOwners.value.get(seasonal.card_id)?.length || 0) > 0 ? seasonal : null
  }
  return filteredCatalogCards.value.find(card => card.base_name === baseName && card.mix_name === mixName) || null
}

function cellView(baseName: string, mixName: string): MatrixCellView {
  const key = matrixKey(baseName, mixName)
  const cell = cardFor(baseName, mixName)
  const owners = cell ? cardOwners.value.get(cell.card_id) || [] : []
  return { state: !cell ? 'empty' : owners.length ? 'pets' : 'card', key, cell, owners }
}

function cellCard(baseName: string, mixName: string): ColorCell {
  const cell = cellView(baseName, mixName).cell
  if (!cell) throw new Error('色卡矩阵访问了空单元格')
  return cell
}

const selectedCell = computed(() => {
  if (!selectedKey.value) return null
  const [baseName, mixName] = selectedKey.value.split('|')
  const view = cellView(baseName || '', mixName || '')
  return view.state === 'empty' ? null : { baseName, mixName, ...view }
})

const selectedCardName = computed(() => {
  const selection = selectedCell.value
  if (!selection) return ''
  if (selection.cell?.card_id === '1000') return '黑白色卡'
  if (selection.baseName === '赛季') return `${selection.mixName} 赛季卡`
  return `${selection.baseName?.replace(/色$/, '')}底 · ${selection.mixName?.replace(/色$/, '')}混`
})

function cardParticle(cardId: string) {
  return particleIds.value.get(cardId)
}

function selectCell(key: string, state: CellState) {
  if (state === 'empty') return
  selectedKey.value = selectedKey.value === key ? '' : key
}

function switchTab(tab: ColorTab) {
  activeTab.value = tab
  selectedKey.value = ''
}

function resetColorsAccount() {
  selectedKey.value = ''
  catalogStatus.value = 'all'
  catalogBase.value = ''
  catalogMix.value = ''
  catalogFiltersOpen.value = false
  resetAccount()
}

defineExpose({ load, pause, resume, resetAccount: resetColorsAccount, error })
watch(() => props.active, value => { if (value) void resume(); else pause() }, { flush: 'sync' })
onMounted(() => { if (props.active) void resume(); else pause() })
</script>

<template>
  <div class="stack colors-page" data-vue-page :aria-busy="loading">
    <section class="panel content-panel full-panel color-page colors-workspace">
      <div class="panel-toolbar color-toolbar">
        <div id="color-tab" class="segmented color-main-tabs" role="tablist" aria-label="色卡视图">
          <button type="button" role="tab" :aria-selected="activeTab === 'owned'" :class="{ active: activeTab === 'owned' }" @click="switchTab('owned')">我的色卡</button>
          <button type="button" role="tab" :aria-selected="activeTab === 'catalog'" :class="{ active: activeTab === 'catalog' }" @click="switchTab('catalog')">完整图鉴</button>
        </div>
        <div v-if="activeTab === 'catalog'" class="color-filters">
          <button id="color-filter-button" type="button" class="ghost-button color-filter-launch" :class="{ active: catalogFiltersOpen || catalogStatus !== 'all' || !!catalogBase || !!catalogMix }" :aria-expanded="catalogFiltersOpen" @click="catalogFiltersOpen = !catalogFiltersOpen">
            <span>图鉴筛选</span><small>{{ catalogFiltersOpen ? '收起' : catalogFilterSummary }}</small>
          </button>
        </div>
        <div class="color-summary" aria-label="色卡统计">
          <span id="color-count" class="count-badge color-count">{{ activeTab === 'owned' ? (data ? `已收录 ${ownedCardCount} / ${data.card_total} 张` : '色卡数据读取中') : (data ? `图鉴 ${filteredCatalogCards.length} / ${catalogCards.length} 张` : '色卡数据读取中') }}</span>
          <span id="color-pet-count" class="color-pet-count">{{ data ? data.pet_total + ' 只精灵' : '—' }}</span>
        </div>
      </div>
      <p class="section-note">底色在横轴、混色在纵轴；鼠标可在整张表格内滚动。</p>

      <div v-if="activeTab === 'catalog' && catalogFiltersOpen" class="catalog-filters color-filter-sheet" aria-label="图鉴筛选">
        <div class="catalog-filter-row" role="group" aria-label="持有状态">
          <span class="catalog-filter-label">状态</span>
          <div class="catalog-filter-options">
            <button v-for="option in catalogStatusOptions" :key="option.value" type="button" class="catalog-filter-chip catalog-status-filter" :class="{ active: catalogStatus === option.value }" :data-value="option.value" :aria-pressed="catalogStatus === option.value" @click="catalogStatus = option.value">{{ option.label }}</button>
          </div>
          <span class="catalog-filter-count">{{ data ? filteredCatalogCards.length + ' / ' + catalogCards.length + ' 款' : '' }}</span>
        </div>
        <div class="catalog-filter-row" role="group" aria-label="底色">
          <span class="catalog-filter-label">底色</span>
          <div class="catalog-filter-options">
            <button type="button" class="catalog-filter-chip catalog-base-filter" :class="{ active: !catalogBase }" data-value="" :aria-pressed="!catalogBase" @click="catalogBase = ''">全部</button>
            <button v-for="base in data?.base_axis || []" :key="base.name" type="button" class="catalog-filter-chip catalog-base-filter" :class="{ active: catalogBase === base.name }" :data-value="base.name" :aria-pressed="catalogBase === base.name" @click="catalogBase = base.name"><i v-if="base.hex" class="swatch" :style="{ background: base.hex }"></i>{{ base.name }}</button>
          </div>
        </div>
        <div class="catalog-filter-row" role="group" aria-label="混色">
          <span class="catalog-filter-label">混色</span>
          <div class="catalog-filter-options">
            <button type="button" class="catalog-filter-chip catalog-mix-filter" :class="{ active: !catalogMix }" data-value="" :aria-pressed="!catalogMix" @click="catalogMix = ''">全部</button>
            <button v-for="mix in data?.mix_axis || []" :key="mix.name" type="button" class="catalog-filter-chip catalog-mix-filter" :class="{ active: catalogMix === mix.name }" :data-value="mix.name" :aria-pressed="catalogMix === mix.name" @click="catalogMix = mix.name"><i v-if="mix.hex" class="swatch" :style="{ background: mix.hex }"></i>{{ displayMixName(mix.name) }}</button>
          </div>
        </div>
      </div>

      <div class="colors-split">
      <div class="colors-matrix-pane">
      <div id="color-matrix" class="color-matrix">
        <div v-if="loading && !data" class="inline-state" role="status"><UiIcon name="clock" />正在加载色卡…</div>
        <div v-else-if="error && !data" class="inline-state" role="alert">色卡加载失败：{{ error }}<button class="ghost-button" @click="load">重试</button></div>
        <div v-else-if="!data" class="inline-state" role="status">暂无色卡数据</div>
        <div v-else-if="activeTab === 'catalog' && !filteredCatalogCards.length" class="inline-state" role="status">当前筛选没有匹配的色卡</div>
        <div v-else id="cl-matrix" class="matrix-grid" :style="{ '--matrix-columns': matrixAxis.base.length }">
          <div class="matrix-cell matrix-axis top left">混色<br>×<br>底色</div>
          <div v-for="base in matrixAxis.base" :key="'top-' + base.name" class="matrix-cell matrix-axis top">
            <div class="axis-label">
              <img v-if="base.name === '黑白'" class="axis-card-preview" src="/static/color-cards/1000.webp" alt="黑白色卡">
              <img v-else-if="base.name === '赛季'" class="axis-card-preview" src="/static/color-cards/season-category.svg" alt="赛季色卡分类">
              <span v-else :style="{ background: base.hex }"></span>
              <b>{{ base.name }}</b>
            </div>
          </div>
          <template v-for="mix in matrixAxis.mix" :key="'row-' + mix.name">
            <div class="matrix-cell matrix-axis left">
              <div class="axis-label">
              <img v-if="specialAxisCards.has(mix.name)" class="axis-card-preview" :src="`/static/color-cards/${specialAxisCards.get(mix.name)}.webp`" :alt="displayMixName(mix.name) + '色卡'">
                <span v-else :style="{ background: mix.hex }"></span>
                <b>{{ displayMixName(mix.name) }}</b>
              </div>
            </div>
            <div v-for="base in matrixAxis.base" :key="base.name + '-' + mix.name" class="matrix-cell matrix-card-cell" :class="{ selected: selectedKey === matrixKey(base.name, mix.name) }" :data-state="cellView(base.name, mix.name).state" :data-mmkey="encodeURIComponent(matrixKey(base.name, mix.name))" :data-card-id="cellView(base.name, mix.name).cell?.card_id" :tabindex="cellView(base.name, mix.name).state === 'empty' ? undefined : 0" :aria-label="base.name + '底色与' + mix.name + '混色'" @click="selectCell(matrixKey(base.name, mix.name), cellView(base.name, mix.name).state)" @keydown.enter.prevent="selectCell(matrixKey(base.name, mix.name), cellView(base.name, mix.name).state)">
              <template v-if="cellView(base.name, mix.name).cell">
                <span class="color-card" role="img" :aria-label="cellCard(base.name, mix.name).names" :title="cellCard(base.name, mix.name).names">
                  <ColorCardFace :card-id="cellCard(base.name, mix.name).card_id" :base-color="cellCard(base.name, mix.name).base_color" :mix-color="cellCard(base.name, mix.name).mix_color" :particle-id="cardParticle(cellCard(base.name, mix.name).card_id)" />
                  <span v-if="cellView(base.name, mix.name).owners.length > 1" class="color-card-count">×{{ cellView(base.name, mix.name).owners.length }}</span>
                </span>
              </template>
              <span v-else class="matrix-empty">—</span>
            </div>
          </template>
        </div>
        <div v-if="data && data.pet_total === 0" id="cl-empty" class="inline-state">宠物库中没有带色卡的宠物</div>
        <div v-if="error && data" class="inline-state matrix-refresh-error" role="alert">色卡刷新失败：{{ error }}<button class="ghost-button small" @click="load">重试</button></div>
      </div>

      <details v-if="activeTab === 'owned'" class="colors-special">
        <summary><span>特殊记录</span><span class="special-counts"><span id="cl-seasonal-count">{{ data ? data.seasonal.length + ' 只赛季卡' : '' }}</span><span id="cl-unknown-count">{{ data ? data.unknown.length + ' 只未收录' : '' }}</span></span></summary>
        <div class="special-records">
          <section id="cl-seasonal" class="special-record-group">
            <div class="special-record-heading"><h3>赛季卡</h3><span class="muted">{{ data ? data.seasonal.length + ' 只' : '' }}</span></div>
            <div class="bl-chips">
              <span v-for="pet in data?.seasonal || []" :key="pet.gid" class="color-owner" :data-mm="pet.gid">
                <img v-if="pet.icon_url && !failed.has(failedKey(pet.gid))" :src="pet.icon_url" alt="" loading="eager" decoding="async" @error="failedIcon(pet.gid)">
                <UiIcon :name="pet.gender === 2 ? 'gender-female' : 'gender-male'" />{{ pet.name }}
              </span>
            </div>
            <div id="cl-seasonal-empty" class="empty-hint" v-show="!!data && !data.seasonal.length">暂无赛季卡</div>
          </section>
          <section id="cl-unknown" class="special-record-group">
            <div class="special-record-heading"><h3>未收录编号</h3><span class="muted">{{ data ? data.unknown.length + ' 只' : '' }}</span></div>
            <div class="bl-chips">
              <span v-for="pet in data?.unknown || []" :key="pet.gid" class="color-owner" :data-mm="pet.gid">
                <img v-if="pet.icon_url && !failed.has(failedKey(pet.gid))" :src="pet.icon_url" alt="" loading="eager" decoding="async" @error="failedIcon(pet.gid)">
                <UiIcon :name="pet.gender === 2 ? 'gender-female' : 'gender-male'" />{{ pet.name }}
                <span class="muted">{{ pet.card_id ? '#' + pet.card_id : '编号未解析' }}</span>
              </span>
            </div>
            <div id="cl-unknown-empty" class="empty-hint" v-show="!!data && !data.unknown.length">全部色卡都已收录</div>
          </section>
        </div>
      </details>
      </div>
      <aside class="colors-selection color-inspector" aria-label="色卡详情">
        <header class="inspector-header">
          <h2>色卡详情</h2>
          <span v-if="selectedCell" class="inspector-status">{{ selectedCell.owners.length ? '已持有' : '未持有' }}</span>
          <button v-if="selectedCell" type="button" class="ghost-button inspector-close" aria-label="关闭色卡详情" @click="selectedKey = ''"><UiIcon name="x" /></button>
        </header>
        <template v-if="selectedCell && selectedCell.cell">
          <div class="inspector-card">
            <span class="color-card inspector-face" role="img" :aria-label="selectedCell.cell.names">
              <ColorCardFace :key="selectedCell.cell.card_id" :card-id="selectedCell.cell.card_id" :base-color="selectedCell.cell.base_color" :mix-color="selectedCell.cell.mix_color" :particle-id="particleIds.get(selectedCell.cell.card_id)" />
            </span>
            <div class="inspector-card-copy"><h3>{{ selectedCardName }}</h3><p>色卡编号 {{ selectedCell.cell.label }}</p></div>
          </div>
          <div class="inspector-count"><span>持有精灵</span><b>{{ selectedCell.owners.length }} 只</b></div>
          <div class="inspector-list-heading"><h3>持有该色卡的精灵</h3><span>点击精灵查看详情</span></div>
          <div class="selection-owners inspector-owners">
            <button v-for="pet in selectedCell.owners" :key="pet.gid" type="button" class="inspector-pet" :data-mm="pet.gid">
              <img v-if="pet.icon_url && !failed.has(failedKey(pet.gid))" class="inspector-pet-icon" :src="pet.icon_url" alt="" decoding="async" @error="failedIcon(pet.gid)">
              <UiIcon :name="pet.gender === 2 ? 'gender-female' : 'gender-male'" />
              <span class="inspector-pet-name">{{ pet.name }}<small>{{ pet.color_card?.particle_name || '暂无花纹数据' }}</small></span>
              <span v-if="pet.color_card" class="color-card inspector-pet-face"><ColorCardFace :card-id="pet.card_id" :base-color="pet.color_card.base_color" :mix-color="pet.color_card.mix_color" :particle-id="pet.color_card.particle_id" /></span>
            </button>
            <p v-if="!selectedCell.owners.length" class="inline-state">当前账号暂未持有这张色卡</p>
          </div>
        </template>
        <div v-else class="inspector-empty">选择色卡格查看持有状态</div>
      </aside>
      </div>
    </section>
  </div>
</template>

<style scoped>
/* 色卡页：整页固定高度，工具栏贴顶、矩阵占满剩余空间，详情面板独立滚动。
   矩阵行高压到 56px，8 列 × 7 行在 1280~1440 下不再把卡片挤成小方块。 */
.colors-page.stack { display: flex; flex-direction: column; gap: 0; max-width: none; height: 100%; min-height: 0; }
.colors-page .panel { margin-bottom: 0; box-shadow: none; }
.colors-workspace { display: flex; flex-direction: column; height: 100%; min-height: 0; padding: 0; overflow: hidden; }

.color-toolbar { flex: none; padding: var(--space-3) var(--space-4); }
.color-main-tabs button { min-height: 28px; padding: 0 var(--space-5); font-size: var(--fs-xs); font-weight: 500; }
.color-main-tabs button.active { font-weight: 600; }
.color-main-tabs button:focus-visible,
.color-filter-launch:focus-visible { outline: 2px solid var(--focus-ring); outline-offset: 2px; }

.color-filters { display: flex; flex: 0 1 228px; align-items: center; min-width: 0; }
.color-filter-launch { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); width: min(100%, 228px); height: 32px; padding: 0 var(--space-2) 0 var(--space-3); border: 1px solid var(--line); border-radius: var(--radius-md); background: var(--panel); color: var(--ink-soft); font-size: var(--fs-xs); font-weight: 500; }
.color-filter-launch span,
.color-filter-launch small { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.color-filter-launch small { flex: none; max-width: 55%; padding: 1px var(--space-2); border-radius: 999px; background: var(--surface-2); color: var(--muted); font-size: var(--fs-3xs); font-weight: 400; }
.color-filter-launch:hover { border-color: var(--teal); background: var(--teal-soft); color: var(--teal-dark); transform: none; }
.color-filter-launch.active { border-color: var(--teal); background: var(--teal-soft); color: var(--teal-dark); }
.color-summary { display: flex; flex: none; align-items: center; gap: var(--space-2); min-width: 0; margin-left: auto; }
.color-count { display: inline-flex; align-items: center; height: 22px; white-space: nowrap; font-variant-numeric: tabular-nums; }
.color-pet-count { display: inline-flex; align-items: center; height: 22px; padding: 0 var(--space-3); border: 1px solid var(--line-soft); border-radius: 999px; background: var(--panel); color: var(--muted); font-size: var(--fs-2xs); white-space: nowrap; }
.section-note { flex: none; margin: 0; padding: var(--space-2) var(--space-4) 0; color: var(--muted); font-size: var(--fs-2xs); line-height: 1.5; }

.catalog-filters { display: flex; flex: none; flex-direction: column; gap: var(--space-1); min-width: 0; margin: var(--space-2) var(--space-4) 0; padding: var(--space-2) var(--space-3); border: 1px solid var(--line-soft); border-radius: var(--radius-md); background: var(--surface-1); }
.catalog-filter-row { display: flex; align-items: center; gap: var(--space-3); min-width: 0; }
.catalog-filter-label { flex: none; width: 28px; color: var(--muted); font-size: var(--fs-2xs); font-weight: 500; }
.catalog-filter-options { display: flex; flex: 1; align-items: center; gap: var(--space-1); min-width: 0; overflow-x: auto; padding: 1px 0; scrollbar-width: thin; }
.catalog-filter-chip { display: inline-flex; flex: none; align-items: center; gap: var(--space-1); min-height: 24px; padding: 0 var(--space-2); border: 1px solid transparent; border-radius: 999px; background: transparent; color: var(--muted); font: inherit; font-size: var(--fs-2xs); white-space: nowrap; cursor: pointer; }
.catalog-filter-chip:hover { border-color: var(--line); background: var(--panel); color: var(--ink); }
.catalog-filter-chip.active { border-color: var(--teal); background: var(--teal-soft); color: var(--teal-dark); font-weight: 600; }
.catalog-filter-chip:focus-visible { outline: 2px solid var(--focus-ring); outline-offset: 1px; }
.catalog-filter-chip .swatch { width: 10px; height: 10px; flex: none; border-radius: 3px; box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--ink) 16%, transparent); }
.catalog-filter-count { flex: none; color: var(--muted-2); font-size: var(--fs-3xs); font-variant-numeric: tabular-nums; }

.colors-split { display: grid; grid-template-columns: minmax(0, 1fr) minmax(300px, 340px); gap: var(--space-4); flex: 1 1 auto; min-width: 0; min-height: 0; padding: var(--space-2) var(--space-4) var(--space-4); }
.colors-matrix-pane { display: flex; flex-direction: column; min-width: 0; min-height: 0; }
.color-matrix { position: relative; display: block; flex: 1 1 auto; min-width: 0; min-height: 110px; overflow: auto; overscroll-behavior: contain; scrollbar-gutter: stable; }
.color-matrix > .inline-state { min-height: 100%; }

.matrix-grid { display: grid; grid-template-columns: 56px repeat(var(--matrix-columns), minmax(72px, 1fr)); width: 100%; min-width: 632px; gap: 1px; border: 1px solid var(--line-soft); border-radius: var(--radius-md); background: var(--line-soft); overflow: clip; }
.matrix-cell { position: relative; display: flex; align-items: center; justify-content: center; min-width: 0; min-height: 56px; padding: var(--space-1); background: var(--panel); }
.matrix-axis { background: var(--surface-1); color: var(--ink-soft); font-size: var(--fs-2xs); font-weight: 500; }
.matrix-axis.top { position: sticky; top: 0; z-index: 3; min-height: 46px; background: var(--surface-2); }
.matrix-axis.left { position: sticky; left: 0; z-index: 2; background: var(--surface-2); }
.matrix-axis.top.left { z-index: 4; flex-direction: column; gap: 2px; color: var(--muted); font-size: var(--fs-3xs); font-weight: 400; line-height: 1.25; text-align: center; }
.axis-label { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: var(--space-1); width: 100%; min-width: 0; }
.axis-label span { display: block; width: 30px; max-width: 100%; height: 16px; border-radius: 4px; box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--ink) 12%, transparent); }
.axis-label b { max-width: 100%; color: var(--ink-soft); font-size: var(--fs-3xs); font-weight: 500; line-height: 1.2; text-align: center; overflow-wrap: anywhere; }
.axis-card-preview { display: block; width: 40px; max-width: 100%; aspect-ratio: 280 / 153; object-fit: contain; border-radius: 5px; }

.matrix-card-cell { flex-direction: column; padding: var(--space-1); }
.matrix-card-cell[data-state='card'] { background: color-mix(in srgb, var(--amber-soft) 30%, var(--panel)); }
.matrix-card-cell[data-state='pets'] { background: color-mix(in srgb, var(--teal-soft) 46%, var(--panel)); }
.matrix-card-cell[data-state='card']:hover,
.matrix-card-cell[data-state='pets']:hover { background: color-mix(in srgb, var(--teal-soft) 66%, var(--panel)); }
.matrix-card-cell:focus-visible { z-index: 1; outline: 2px solid var(--focus-ring); outline-offset: -2px; }
.matrix-card-cell.selected { z-index: 1; outline: 2px solid var(--teal); outline-offset: -2px; background: var(--teal-soft); }
.matrix-empty { align-self: center; color: var(--muted-2); font-size: var(--fs-xs); opacity: .5; }

.color-card { position: relative; display: block; width: min(100%, 126px); aspect-ratio: 280 / 153; margin: auto; overflow: hidden; border-radius: var(--radius-sm); background: var(--surface-2); box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--ink) 12%, transparent); cursor: pointer; isolation: isolate; }
.color-card-count { position: absolute; right: 4px; bottom: 4px; z-index: 3; padding: 1px 5px; border-radius: 999px; background: color-mix(in srgb, var(--teal-deep) 88%, transparent); color: var(--white); font-size: var(--fs-3xs); font-weight: 600; font-variant-numeric: tabular-nums; }

.color-inspector { display: flex; flex-direction: column; min-width: 0; min-height: 0; overflow-y: auto; border: 1px solid var(--line-soft); border-radius: var(--radius-lg); background: var(--panel); color: var(--ink); scrollbar-gutter: stable; }
.inspector-header { display: flex; flex: none; align-items: center; gap: var(--space-2); padding: var(--space-3) var(--space-4); border-bottom: 1px solid var(--line-soft); }
.inspector-header h2 { flex: 1; margin: 0; font-size: var(--fs-sm); font-weight: 600; }
.inspector-status { padding: 2px var(--space-2); border-radius: 999px; background: var(--surface-2); color: var(--muted); font-size: var(--fs-3xs); white-space: nowrap; }
.inspector-close { display: grid; flex: none; place-items: center; width: 26px; height: 26px; padding: 0; border-radius: var(--radius-sm); background: var(--surface-2); color: var(--muted); }
.inspector-close:hover { background: var(--surface-3); color: var(--ink); }
.inspector-close:focus-visible { outline: 2px solid var(--focus-ring); outline-offset: 2px; }
.inspector-card { display: flex; flex: none; align-items: center; gap: var(--space-4); padding: var(--space-4); }
.inspector-face { flex: 0 0 46%; width: 46%; max-width: 168px; margin: 0; cursor: default; }
.inspector-card-copy { min-width: 0; overflow-wrap: anywhere; }
.inspector-card-copy h3 { margin: 0 0 var(--space-1); font-size: var(--fs-md); font-weight: 600; line-height: 1.3; }
.inspector-card-copy p { margin: 0; color: var(--muted); font-size: var(--fs-2xs); }
.inspector-count { display: flex; flex: none; align-items: baseline; justify-content: space-between; gap: var(--space-3); margin: 0 var(--space-4); padding: var(--space-3) 0; border-block: 1px solid var(--line-soft); color: var(--muted); font-size: var(--fs-xs); }
.inspector-count b { color: var(--ink); font-size: var(--fs-sm); font-weight: 600; font-variant-numeric: tabular-nums; }
.inspector-list-heading { display: flex; flex: none; flex-wrap: wrap; align-items: baseline; gap: var(--space-2); padding: var(--space-3) var(--space-4) var(--space-2); }
.inspector-list-heading h3 { margin: 0; font-size: var(--fs-xs); font-weight: 600; }
.inspector-list-heading span { color: var(--muted); font-size: var(--fs-3xs); }
.inspector-owners { display: flex; flex: 1 1 auto; flex-direction: column; gap: var(--space-1); min-width: 0; min-height: 0; overflow-y: auto; padding: 0 var(--space-4) var(--space-4); }
.inspector-pet { display: flex; width: 100%; align-items: center; gap: var(--space-2); padding: var(--space-2); border: 1px solid var(--line-soft); border-radius: var(--radius-md); background: var(--panel); color: var(--ink); font: inherit; font-size: var(--fs-xs); text-align: left; cursor: pointer; }
.inspector-pet:hover { border-color: var(--line); background: var(--surface-1); }
.inspector-pet:focus-visible { outline: 2px solid var(--focus-ring); outline-offset: -2px; }
.inspector-pet-icon { width: 30px; height: 30px; flex: none; object-fit: contain; }
.inspector-pet > .ui-icon { width: 15px; height: 15px; flex: none; color: var(--muted); }
.inspector-pet-name { flex: 1; min-width: 0; overflow-wrap: anywhere; }
.inspector-pet-name small { display: block; margin-top: 1px; color: var(--muted); font-size: var(--fs-3xs); }
.color-card.inspector-pet-face { width: 44px; flex: none; margin: 0; border-radius: 5px; cursor: default; }
.inspector-owners > .inline-state { flex: 1; }
.inspector-empty { display: flex; flex: 1; flex-direction: column; align-items: center; justify-content: center; gap: var(--space-3); padding: var(--space-6); color: var(--muted); font-size: var(--fs-xs); line-height: 1.6; text-align: center; }
.inspector-empty::before { content: ''; width: 52px; height: 52px; border-radius: var(--radius-lg); background: radial-gradient(circle at 50% 50%, var(--teal-soft) 0 9px, transparent 9px), repeating-linear-gradient(0deg, transparent 0 12px, var(--line-soft) 12px 13px), repeating-linear-gradient(90deg, transparent 0 12px, var(--line-soft) 12px 13px), var(--surface-1); box-shadow: inset 0 0 0 1px var(--line-soft); }

.inline-state { display: flex; flex: none; align-items: center; justify-content: center; gap: var(--space-2); min-height: 44px; padding: var(--space-3); color: var(--muted); font-size: var(--fs-xs); text-align: center; }
.inline-state .ghost-button { margin-left: var(--space-2); }
.inline-state[role='alert'] { border-radius: var(--radius-md); background: var(--danger-soft); color: var(--danger-ink); }
.matrix-refresh-error { margin-top: var(--space-2); border-radius: var(--radius-md); background: var(--danger-soft); color: var(--danger-ink); }

.colors-special { flex: none; margin-top: var(--space-2); border: 1px solid var(--line-soft); border-radius: var(--radius-md); background: var(--surface-1); }
.colors-special summary { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); min-height: 34px; padding: 0 var(--space-3); color: var(--ink-soft); font-size: var(--fs-xs); font-weight: 500; cursor: pointer; list-style: none; }
.colors-special summary::-webkit-details-marker { display: none; }
.colors-special summary::after { content: '展开'; color: var(--muted-2); font-size: var(--fs-2xs); font-weight: 400; }
.colors-special[open] summary::after { content: '收起'; }
.special-counts { display: flex; flex-wrap: wrap; gap: var(--space-3); margin-left: auto; color: var(--muted); font-size: var(--fs-3xs); font-weight: 400; }
.special-records { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-2); padding: 0 var(--space-3) var(--space-3); }
.special-record-group { min-width: 0; padding: var(--space-3); border: 1px solid var(--line-soft); border-radius: var(--radius-sm); background: var(--panel); }
.special-record-heading { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); margin-bottom: var(--space-2); }
.special-record-heading h3 { margin: 0; font-size: var(--fs-xs); font-weight: 600; }
.special-record-heading .muted { color: var(--muted); font-size: var(--fs-3xs); }
.special-record-group .bl-chips { display: flex; flex-wrap: wrap; gap: var(--space-1); min-height: 26px; }
.color-owner { display: inline-flex; min-width: 0; align-items: center; gap: var(--space-1); padding: 2px var(--space-2) 2px 2px; border: 1px solid var(--line-soft); border-radius: 999px; background: var(--surface-1); color: var(--ink-soft); font-size: var(--fs-3xs); overflow-wrap: anywhere; }
.color-owner img { width: 20px; height: 20px; flex: none; object-fit: contain; border-radius: 50%; background: var(--surface-2); }
.color-owner .ui-icon { width: 12px; height: 12px; flex: none; color: var(--muted); }
.color-owner .muted { color: var(--muted); }
.empty-hint { color: var(--muted); font-size: var(--fs-2xs); }

@media (max-width: 1360px) {
  .colors-split { grid-template-columns: minmax(0, 1fr) 312px; }
}
@media (max-width: 1000px) {
  .colors-split { grid-template-columns: minmax(0, 1fr); grid-template-rows: minmax(0, 1.15fr) minmax(0, .85fr); gap: var(--space-2); padding: var(--space-2) var(--space-3) var(--space-3); }
  .color-filters { flex-basis: 200px; }
  .inspector-card { padding-block: var(--space-3); }
  .inspector-face { flex-basis: 140px; width: 140px; }
  .special-records { grid-template-columns: minmax(0, 1fr); }
}
@media (max-width: 760px) {
  .color-filters { flex-basis: 100%; }
  .color-filter-launch { width: 100%; }
  .color-summary { width: 100%; margin-left: 0; }
  .colors-split { grid-template-rows: minmax(0, 1fr) minmax(0, .9fr); }
}
</style>
