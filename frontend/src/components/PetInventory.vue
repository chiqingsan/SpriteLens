<script setup lang="ts">
import { computed, nextTick, onBeforeUpdate, onUpdated, ref } from 'vue'
import type { PetsModel } from '../composables/usePets'
import type { PetView } from '../types/pets'
import PetCards from './PetCards.vue'
import PetSlots from './PetSlots.vue'
import PetTable from './PetTable.vue'
import PetBoxNavigation from './PetBoxNavigation.vue'
import UiIcon from './UiIcon.vue'
import PetDetailPanel from './PetDetailPanel.vue'
const { model } = defineProps<{ model: PetsModel; imageMode: () => string }>()
const { view, data, busy, error, box, teams, pets, pages, page, selected } = model
const emit = defineEmits<{ select: [gid: number, element: HTMLElement]; close: [preserve?: boolean]; view: [value: PetView]; reset: [] }>()
const wrap = ref<HTMLElement | null>(null)
let scrollTop = 0, scrollLeft = 0
const detailOpen = ref(false), trigger = ref<HTMLElement | null>(null)
const visibleGids = computed(() => view.value === 'point' ? model.slots.value.filter(slot => slot.state === 'matched').map(slot => slot.gid!) : (view.value === 'card' ? model.cards.value : pets.value).map(pet => pet.gid))
let focusedGid: string | undefined
onBeforeUpdate(() => { focusedGid = wrap.value?.contains(document.activeElement) ? (document.activeElement as HTMLElement).dataset.gid : undefined })
onUpdated(() => { if (focusedGid) wrap.value?.querySelector<HTMLElement>(`[data-gid="${focusedGid}"]`)?.focus({ preventScroll: true }) })
const empty = computed(() => view.value === 'point' ? teams.value ? !data.value?.backpack.teams.length : !box.value : !pets.value.length)
const emptyText = computed(() => view.value === 'point'
  ? teams.value ? '尚未采集出战队伍，登录游戏后同步。' : data.value?.backpack.boxes.length ? '已采集的箱子均为空箱，可切换出战背包查看队伍。' : '尚未采集游戏箱表。登录游戏后同步，可切换属性卡片或对比表格查看已采集精灵。'
  : data.value?.total ? '没有符合筛选条件的精灵，可清除筛选后查看全部。' : '暂无精灵数据：开始采集后登录游戏，等待数据同步。')
const pageNumbers = computed(() => {
  const values = [1, ...Array.from({ length: 5 }, (_, index) => page.value - 2 + index).filter(value => value > 1 && value < pages.value), pages.value]
  return [...new Set(values)].sort((a, b) => a - b)
})
function select(gid: number, element: HTMLElement | null) { selected.value = gid; trigger.value = element; detailOpen.value = true; if (element) emit('select', gid, element) }
function closeDetail(preserve = false) { detailOpen.value = false; if (!preserve) selected.value = null }
async function setBox(id: number) {
  closeDetail(true); emit('close', true); model.setBox(id)
  await nextTick()
  if (wrap.value) { wrap.value.scrollTop = 0; wrap.value.scrollLeft = 0 }
  const root = wrap.value?.parentElement
  const target = wrap.value?.querySelector<HTMLElement>(`[data-gid="${selected.value}"]`) || root?.querySelector<HTMLElement>(`[data-box="${id}"]`)
  target?.focus({ preventScroll: true })
}
function setPage(value: number) { closeDetail(); emit('close'); page.value = value; if (wrap.value) wrap.value.scrollTop = 0 }
function locate(id: number) { model.setView('point'); emit('view', 'point'); void setBox(id) }
defineExpose({ setBox, closeDetail, openDetail: () => { if (selected.value !== null) detailOpen.value = true },
  saveScroll: () => { scrollTop = wrap.value!.scrollTop; scrollLeft = wrap.value!.scrollLeft },
  restoreScroll: () => { wrap.value!.scrollTop = scrollTop; wrap.value!.scrollLeft = scrollLeft } })
</script>

<template>
  <Teleport to="#pet-view">
    <button v-for="item in ([['point', '游戏箱位'], ['card', '属性卡片'], ['table', '对比表格']] as const)" :key="item[0]" :data-view="item[0]" :class="{ active: view === item[0] }" :aria-pressed="view === item[0]" @click="closeDetail(); emit('close'); model.setView(item[0]); emit('view', item[0])"><UiIcon :name="item[0] === 'table' ? 'table' : 'layout-grid'"></UiIcon>{{ item[1] }}</button>
  </Teleport>
  <Teleport to="#pet-count-root"><span id="pet-count" class="count-badge" role="status">{{ data ? '命中 ' + (data?.shown || 0) + ' / ' + (data?.total || 0) + ' 只' : error ? '加载失败' : '加载中…' }}</span></Teleport>
  <PetBoxNavigation v-show="view === 'point'" :model="model" @select="setBox"></PetBoxNavigation>
  <div ref="wrap" class="table-wrap" :aria-busy="busy">
    <div id="pet-grid" class="pet-grid" :class="{ 'point-grid game-box-grid': view === 'point', 'box-fill-grid': view === 'point' && !teams }" :hidden="view === 'table'" :aria-busy="busy">
      <PetSlots v-if="view === 'point'" :slots="model.slots.value" :pets="model.byGid.value" :selected="selected" :teams="teams" :active-team="data?.backpack.active_team || 0" :image-mode="imageMode()" @select="select"></PetSlots>
      <PetCards v-if="view === 'card'" :pets="model.cards.value" :selected="selected" :image-mode="imageMode()" @select="select"></PetCards>
    </div>
      <PetTable v-if="view === 'table'" :pets="pets" :selected="selected" :image-mode="imageMode()" @select="select"></PetTable>
    <div id="pet-empty" class="empty-hint" role="status" :hidden="!empty && !error">
      <p id="pet-empty-copy">{{ error ? '精灵数据加载失败：' + error : emptyText }}</p>
      <div class="button-row"><button v-if="error" id="btn-pets-retry" class="ghost-button small" @click="model.load(false)"><UiIcon name="refresh"></UiIcon>重试</button><button id="btn-empty-reset" class="ghost-button small" :hidden="!!error || view === 'point' || !!pets.length || !data?.total" @click="emit('reset')"><UiIcon name="filter-off"></UiIcon>清除筛选</button></div>
    </div>
  </div>
  <div id="pet-pager" class="pager" :hidden="view !== 'card' || !pets.length">
    <button :disabled="page === 1" @click="setPage(page - 1)">上一页</button>
    <template v-for="(number, index) in pageNumbers" :key="number"><span v-if="index && number - pageNumbers[index - 1]! > 1">…</span><button :data-page="number" :class="{ active: page === number }" :aria-current="page === number ? 'page' : undefined" @click="setPage(number)">{{ number }}</button></template>
    <button :disabled="page === pages" @click="setPage(page + 1)">下一页</button><span class="pager-info">浏览页 {{ page }} / {{ pages }} · 每页 60 只</span>
  </div>
  <PetDetailPanel :model="model" :open="detailOpen" :enabled="model.visible.value" :trigger="trigger" :visible-gids="visibleGids" :image-mode="imageMode()" @close="closeDetail()" @select="select" @locate="locate"></PetDetailPanel>
</template>
