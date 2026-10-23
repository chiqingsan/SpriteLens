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
.colors-page { max-width: none; height: 100%; min-width: 0; min-height: 0; overflow: hidden; padding: 0; }
.colors-page .panel { margin-bottom: 0; box-shadow: none; }
.colors-workspace { display: flex; flex-direction: column; min-width: 0; min-height: 0; height: 100%; padding: 0; overflow: hidden; }
.color-toolbar { display: flex; flex: none; flex-wrap: wrap; align-items: center; gap: 10px; min-width: 0; padding: var(--space-3) var(--space-4); border-bottom: 1px solid var(--line-soft); overflow: visible; }
.color-main-tabs { display: flex; flex: 0 0 auto; gap: 0; padding: 2px; border: 1px solid var(--line-soft); border-radius: var(--radius-md); background: var(--surface-2); }
.color-main-tabs button { min-height: 42px; padding: 0 var(--space-5); border: 0; border-radius: calc(var(--radius-md) - 2px); background: transparent; color: var(--muted); font: inherit; font-size: var(--fs-sm); white-space: nowrap; cursor: pointer; }
.color-main-tabs button.active { background: var(--teal); color: var(--white); font-weight: 700; }
.color-main-tabs button:focus-visible, .color-filter-launch:focus-visible { outline: 2px solid var(--focus-ring); outline-offset: 2px; }
.color-filters { display: flex; flex: 0 1 250px; align-items: center; min-width: 0; }
.color-filter-launch { display: flex; width: min(100%, 250px); height: 42px; align-items: center; justify-content: space-between; gap: var(--space-3); padding: 0 var(--space-3); border: 1px solid var(--line); border-radius: var(--radius-md); background: var(--surface-1); color: var(--teal-dark); font-size: var(--fs-xs); }
.color-filter-launch span, .color-filter-launch small { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.color-filter-launch small { color: var(--muted); font-size: var(--fs-3xs); }
.color-filter-launch.active { border-color: var(--teal); background: var(--teal-soft); }
.color-filter-launch:hover { border-color: var(--teal); background: var(--teal-soft); box-shadow: none; transform: none; }
.color-summary { display: flex; flex: none; align-items: center; gap: 8px; margin-left: auto; }
.color-count, .color-pet-count { white-space: nowrap; }
.color-pet-count { padding: 7px 10px; border: 1px solid var(--line-soft); border-radius: 999px; color: var(--muted); font-size: var(--fs-2xs); }
.section-note { flex: none; min-height: 32px; margin: 0; padding: var(--space-2) var(--space-4); border-bottom: 1px solid var(--line-soft); color: var(--muted); font-size: var(--fs-2xs); }
.catalog-filters { display: flex; flex: none; flex-direction: column; gap: var(--space-1); min-width: 0; margin: var(--space-3) var(--space-4) 0; padding: var(--space-2) var(--space-3); border: 1px solid var(--line-soft); border-radius: var(--radius-md); background: var(--surface-2); }
.catalog-filter-row { display: flex; min-width: 0; align-items: center; gap: var(--space-3); }
.catalog-filter-label { flex: none; min-width: 32px; color: var(--muted); font-size: var(--fs-2xs); font-weight: 700; }
.catalog-filter-options { display: flex; min-width: 0; flex: 1; align-items: center; gap: var(--space-1); overflow-x: auto; padding: 1px 0; }
.catalog-filter-chip { display: inline-flex; flex: none; min-height: 28px; align-items: center; gap: var(--space-1); padding: 0 var(--space-3); border: 1px solid transparent; border-radius: 999px; background: var(--surface-1); color: var(--muted); font: inherit; font-size: var(--fs-2xs); cursor: pointer; }
.catalog-filter-chip.active { border-color: var(--teal); background: var(--teal); color: var(--white); font-weight: 700; }
.catalog-filter-chip:focus-visible { outline: 2px solid var(--teal); outline-offset: 1px; }
.catalog-filter-count { flex: none; color: var(--muted-2); font-size: var(--fs-3xs); }
.colors-split { display: grid; grid-template-columns: minmax(0, 7fr) minmax(280px, 3fr); flex: 1; min-height: 0; min-width: 0; gap: 12px; padding: 12px; }
.colors-matrix-pane { display: flex; flex-direction: column; min-width: 0; min-height: 0; }
.color-inspector { display: flex; flex-direction: column; min-width: 0; min-height: 0; border: 1px solid var(--line); border-radius: var(--radius-md); background: var(--panel); color: var(--ink); overflow-y: auto; }
.inspector-header { display: flex; align-items: center; flex: none; gap: 8px; padding: 12px; border-bottom: 1px solid var(--line-soft); }
.inspector-header h2 { flex: 1; font-size: var(--fs-sm); margin: 0; }
.inspector-status { border-radius: 999px; padding: 4px 10px; background: var(--teal-soft); color: var(--teal-dark); font-size: var(--fs-2xs); }
.inspector-close { display: grid; place-items: center; width: 30px; height: 30px; padding: 4px; flex: none; }
.inspector-card { display: flex; flex: none; align-items: center; gap: 16px; padding: 20px 12px; }
.inspector-face { flex: 0 0 48%; margin: 0; }
.inspector-card-copy { min-width: 0; overflow-wrap: anywhere; }
.inspector-card-copy h3 { margin: 0 0 8px; font-size: 24px; }
.inspector-card-copy p { margin: 0; color: var(--muted); font-size: var(--fs-xs); }
.inspector-count { display: flex; flex: none; justify-content: space-between; padding: 16px 0; margin: 0 12px; border-block: 1px solid var(--line-soft); font-size: var(--fs-xs); }
.inspector-list-heading { display: flex; flex: none; flex-wrap: wrap; align-items: baseline; gap: 8px; padding: 16px 12px 8px; }
.inspector-list-heading h3 { margin: 0; font-size: var(--fs-xs); }
.inspector-list-heading span { color: var(--muted); font-size: var(--fs-3xs); }
.inspector-owners { min-width: 0; min-height: 0; flex: 1; overflow-y: auto; padding: 0 12px 12px; }
.inspector-pet { display: flex; width: 100%; align-items: center; gap: 6px; padding: 10px 8px; margin-bottom: 4px; border: 1px solid var(--line-soft); border-radius: var(--radius-md); background: transparent; color: var(--ink); font: inherit; font-size: var(--fs-xs); text-align: left; cursor: pointer; }
.inspector-pet:hover { background: var(--teal-soft); }
.inspector-pet:focus-visible, .inspector-close:focus-visible { outline: 2px solid var(--focus-ring); outline-offset: -2px; }
.inspector-pet-icon { width: 28px; height: 28px; object-fit: contain; flex: none; }
.inspector-pet .ui-icon { width: 16px; height: 16px; flex: none; }
.inspector-pet-name { flex: 1; min-width: 0; overflow-wrap: anywhere; }
.inspector-pet-name small { display: block; color: var(--muted); font-size: var(--fs-3xs); }
.color-card.inspector-pet-face { width: 44px; flex: none; margin: 0; border-radius: 6px; }
.inspector-empty { display: grid; flex: 1; place-items: center; padding: 24px; color: var(--muted); text-align: center; font-size: var(--fs-xs); }
.color-matrix { display: flex; flex: 1 1 auto; flex-direction: column; min-width: 0; min-height: 0; padding: 0 10px var(--space-3); overflow: auto; scrollbar-gutter: stable; overscroll-behavior: contain; }
.matrix-grid { display: grid; grid-template-columns: 64px repeat(var(--matrix-columns), minmax(90px, 1fr)); width: 100%; min-width: 800px; border-top: 1px solid var(--line); border-left: 1px solid var(--line); }
.matrix-cell { position: relative; display: flex; min-width: 0; min-height: 92px; align-items: center; justify-content: center; padding: 6px; border-right: 1px solid var(--line); border-bottom: 1px solid var(--line); }
.matrix-axis { z-index: 1; background: var(--surface-2); color: var(--ink-soft); font-size: var(--fs-2xs); font-weight: 800; }
.matrix-axis.top { position: sticky; top: 0; z-index: 3; min-height: 78px; background: color-mix(in srgb, var(--teal-soft) 42%, var(--surface-2)); }
.matrix-axis.left { position: sticky; left: 0; z-index: 2; }
.matrix-axis.top.left { z-index: 4; }
.axis-label { display: grid; width: 100%; height: 100%; grid-template-rows: 1fr 1fr; align-items: center; justify-items: center; gap: 3px; }
.axis-label span { display: block; width: 42%; height: 75%; min-height: 20px; border-radius: var(--radius-sm); box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--ink) 10%, transparent); }
.matrix-axis.left .axis-label span { width: 66%; }
.axis-label b { font-size: var(--fs-xs); }
.axis-card-preview { display: block; width: 52px; max-width: 100%; aspect-ratio: 280 / 153; object-fit: contain; border-radius: 7px; }
.matrix-card-cell { align-items: flex-start; flex-direction: column; justify-content: center; background: var(--panel); }
.matrix-card-cell[data-state='card'] { background: color-mix(in srgb, var(--amber-soft) 12%, var(--panel)); }
.matrix-card-cell[data-state='pets'] { background: color-mix(in srgb, var(--teal-soft) 16%, var(--panel)); }
.matrix-card-cell:hover, .matrix-card-cell:focus-visible { background: var(--teal-soft); }
.matrix-card-cell:focus-visible { outline: 2px solid var(--focus-ring); outline-offset: -2px; }
.matrix-card-cell.selected { outline: 2px solid var(--teal); outline-offset: -2px; box-shadow: inset 3px 0 0 var(--teal); }
.matrix-empty { align-self: center; color: var(--muted-2); font-size: var(--fs-xs); }
.color-card { position: relative; display: block; width: min(100%, 150px); aspect-ratio: 280 / 153; margin: auto; overflow: hidden; border-radius: 15px; background: var(--surface-1); box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--ink) 10%, transparent); cursor: pointer; isolation: isolate; }
.color-card-count { position: absolute; right: 5px; bottom: 5px; z-index: 3; padding: 2px 6px; border-radius: 999px; background: var(--teal-dark); color: var(--white); font-size: var(--fs-3xs); font-weight: 800; }
.color-owner { display: inline-flex; min-width: 0; align-items: center; gap: 4px; padding: 3px 5px; border: 1px solid var(--line-soft); border-radius: var(--radius-sm); background: var(--surface-1); color: var(--ink-soft); font-size: var(--fs-3xs); overflow-wrap: anywhere; }
.color-owner img { width: 20px; height: 20px; flex: none; object-fit: contain; }
.color-owner .ui-icon { width: 13px; height: 13px; flex: none; }
.color-owner small { color: var(--muted); }
.inline-state { display: flex; flex: none; min-height: 48px; align-items: center; justify-content: center; gap: var(--space-3); padding: var(--space-4); color: var(--muted); font-size: var(--fs-xs); }
.matrix-refresh-error { justify-content: flex-start; }
.colors-special { flex: none; margin: 0 var(--space-4) var(--space-3); border: 1px solid var(--line-soft); border-radius: var(--radius-md); background: var(--surface-1); }
.colors-special summary { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); min-height: 34px; padding: 0 var(--space-3); color: var(--ink-soft); font-size: var(--fs-xs); font-weight: 700; cursor: pointer; list-style: none; }
.colors-special summary::-webkit-details-marker { display: none; }
.colors-special summary::after { content: '展开'; color: var(--muted-2); font-size: var(--fs-2xs); font-weight: 400; }
.colors-special[open] summary::after { content: '收起'; }
.special-counts { display: flex; flex-wrap: wrap; gap: var(--space-3); margin-left: auto; color: var(--muted); font-weight: 400; }
.special-records { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-3); padding: 0 var(--space-3) var(--space-3); }
.special-record-group { min-width: 0; padding: var(--space-3); border: 1px solid var(--line-soft); border-radius: var(--radius-md); background: var(--surface-2); }
.special-record-heading { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); margin-bottom: var(--space-2); }
.special-record-heading h3 { font-size: var(--fs-xs); }
.special-record-group .bl-chips { display: flex; flex-wrap: wrap; gap: var(--space-1); min-height: 30px; }
.empty-hint { color: var(--muted); font-size: var(--fs-2xs); }
@media (max-width: 960px) {
  .colors-page { padding: 0; }
  .color-toolbar { padding: var(--space-3) var(--space-4); }
  .color-filters { flex-basis: 200px; }
  .colors-split { grid-template-columns: minmax(0, 1fr) 280px; }
  .colors-special { margin-left: var(--space-4); margin-right: var(--space-4); }
  .special-records { grid-template-columns: minmax(0, 1fr); }
}
@media (max-width: 640px) {
  .color-toolbar { align-items: stretch; }
  .color-main-tabs { width: 100%; }
  .color-main-tabs button { flex: 1; }
  .color-filters { flex-basis: 100%; }
  .color-filter-launch { width: 100%; }
  .color-summary { width: 100%; margin-left: 0; }
  .section-note { padding-inline: var(--space-4); }
  .colors-split { grid-template-columns: minmax(0, 1fr); grid-template-rows: minmax(180px, 1fr) minmax(160px, 0.8fr); padding: 8px; gap: 8px; }
  .inspector-card { padding-block: 12px; }
  .inspector-face { flex-basis: 100px; }
  .inspector-card-copy h3 { font-size: 18px; }
  .inspector-count { padding-block: 8px; }
}
</style>
