<script setup lang="ts">
import { computed, nextTick, onBeforeUpdate, onUpdated, ref } from 'vue'
import type { PetsModel } from '../composables/usePets'
import type { PetView } from '../types/pets'
import PetSlots from './PetSlots.vue'
import PetBoxNavigation from './PetBoxNavigation.vue'
import PetPageNavigation from './PetPageNavigation.vue'
import UiIcon from './UiIcon.vue'
import UiSegmented from './UiSegmented.vue'
import PetDetailPanel from './PetDetailPanel.vue'
const { model } = defineProps<{ model: PetsModel }>()
const { view, data, busy, error, box, teams, pets, page, selected } = model
const emit = defineEmits<{ select: [gid: number, element: HTMLElement]; close: [preserve?: boolean]; view: [value: PetView]; reset: [] }>()
const wrap = ref<HTMLElement | null>(null)
let scrollTop = 0, scrollLeft = 0
const detailOpen = ref(false), trigger = ref<HTMLElement | null>(null)
let focusedGid: string | undefined
onBeforeUpdate(() => { focusedGid = wrap.value?.contains(document.activeElement) ? (document.activeElement as HTMLElement).dataset.gid : undefined })
onUpdated(() => { if (focusedGid) wrap.value?.querySelector<HTMLElement>(`[data-gid="${focusedGid}"]`)?.focus({ preventScroll: true }) })
const empty = computed(() => view.value === 'point' ? teams.value ? !data.value?.backpack.teams.length : !box.value : !pets.value.length)
const emptyText = computed(() => busy.value && !data.value ? '正在加载精灵背包…' : view.value === 'point'
  ? teams.value ? '尚未采集出战队伍，登录游戏后同步。' : data.value?.backpack.boxes.length ? '已采集的箱子均为空箱，可切换出战背包查看队伍。' : '尚未采集游戏箱表。登录游戏后同步，可切换自定义排序查看已采集精灵。'
  : data.value?.total ? '没有符合筛选条件的精灵，可清除筛选后查看全部。' : '暂无精灵数据：开始采集后登录游戏，等待数据同步。')
function select(gid: number, element: HTMLElement | null) { selected.value = gid; trigger.value = element; detailOpen.value = true; if (element) emit('select', gid, element) }
function selectGid(gid: number) {
  if (!model.find(gid)) return false
  selected.value = gid
  trigger.value = null
  detailOpen.value = true
  return true
}
function reveal(gid: string) {
  const index = pets.value.findIndex(pet => String(pet.gid) === gid)
  if (index < 0) return false
  model.setView('card')
  page.value = Math.floor(index / 30) + 1
  return selectGid(pets.value[index]!.gid)
}
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
function openTeams() { closeDetail(); emit('close'); model.setView('point'); emit('view', 'point'); void setBox(0) }
function locate(id: number) { model.setView('point'); emit('view', 'point'); void setBox(id) }
defineExpose({ setBox, reveal, closeDetail, openDetail: () => { if (selected.value !== null) detailOpen.value = true },
  selectGid,
  saveScroll: () => { scrollTop = wrap.value!.scrollTop; scrollLeft = wrap.value!.scrollLeft },
  restoreScroll: () => { wrap.value!.scrollTop = scrollTop; wrap.value!.scrollLeft = scrollLeft } })
</script>

<template>
  <Teleport to="#pet-view">
    <UiSegmented aria-label="背包视图">
    <button v-for="item in ([['point', '游戏箱位'], ['card', '自定义排序']] as const)" :key="item[0]" :data-view="item[0]" :class="{ active: view === item[0] }" :aria-pressed="view === item[0]" @click="closeDetail(); emit('close'); model.setView(item[0]); emit('view', item[0])"><UiIcon name="layout-grid"></UiIcon>{{ item[1] }}</button>
    </UiSegmented>
  </Teleport>
  <Teleport to="#pet-count-root"><span id="pet-count" class="count-badge" role="status">{{ data ? '命中 ' + (data?.shown || 0) + ' / ' + (data?.total || 0) + ' 只' : error ? '加载失败' : '加载中…' }}</span></Teleport>
  <PetBoxNavigation v-show="view === 'point'" :model="model" @select="setBox"></PetBoxNavigation>
  <PetPageNavigation v-show="view === 'card' && !!pets.length" :model="model" @select="setPage" @teams="openTeams"></PetPageNavigation>
  <div ref="wrap" class="table-wrap" :class="{ 'pet-empty-state': empty && (!busy || !data) }" :aria-busy="busy">
    <div id="pet-grid" class="pet-grid" :class="{ 'point-grid game-box-grid': view === 'point' || view === 'card', 'box-fill-grid': (view === 'point' && !teams) || view === 'card', 'pet-teams-view': view === 'point' && teams }" :aria-busy="busy">
      <PetSlots :slots="view === 'point' ? model.slots.value : model.cardSlots.value" :pets="model.byGid.value" :selected="selected" :teams="view === 'point' && teams" :active-team="view === 'point' ? data?.backpack.active_team || 0 : 0" @select="select"></PetSlots>
    </div>
    <div id="pet-empty" class="empty-hint" role="status" :hidden="!empty && !error">
      <UiIcon :name="error ? 'search' : busy && !data ? 'clock' : 'layout-grid'" />
      <p id="pet-empty-copy">{{ error ? '精灵数据加载失败：' + error : emptyText }}</p>
      <div class="button-row"><button v-if="error" id="btn-pets-retry" class="ghost-button small" @click="model.load(false)"><UiIcon name="refresh"></UiIcon>重试</button><button id="btn-empty-reset" class="ghost-button small" :hidden="!!error || view === 'point' || !!pets.length || !data?.total" @click="emit('reset')"><UiIcon name="filter-off"></UiIcon>清除筛选</button></div>
    </div>
  </div>
  <PetDetailPanel :model="model" :open="detailOpen" :enabled="model.visible.value" :trigger="trigger" @close="closeDetail()" @locate="locate"></PetDetailPanel>
</template>
