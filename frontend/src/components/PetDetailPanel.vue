<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import type { PetsModel } from '../composables/usePets'
import PageInspector from './PageInspector.vue'
import PetDetail from './PetDetail.vue'
import './pet-detail.css'
const props = defineProps<{ model: PetsModel; open: boolean; enabled: boolean; trigger: HTMLElement | null }>()
const emit = defineEmits<{ close: [restore?: boolean]; locate: [id: number] }>()
const pet = computed(() => props.model.selected.value === null ? null : props.model.find(props.model.selected.value))
const loadedDetail = computed(() => {
  const loaded = props.model.detail.value
  return loaded && loaded.uid === props.model.data.value?.uid ? loaded : null
})
const detailedPet = computed(() => loadedDetail.value?.pet ?? null)
const detailIsCurrent = computed(() => {
  const loaded = loadedDetail.value, snapshot = props.model.data.value
  return loaded !== null && loaded.gid === pet.value?.gid && loaded.version >= (snapshot?.version || 0)
})
// 与图鉴详情保持同一策略：请求新详情期间保留上一份完整数据，
// 标题、定位按钮和内容一起在新详情到达后替换，避免出现新旧数据拼接。
const panelPet = computed(() => detailedPet.value ?? pet.value)
const place = computed(() => panelPet.value?.location ?? null)
const showing = computed(() => props.open && props.enabled && !!pet.value)
const inspector = ref<InstanceType<typeof PageInspector> | null>(null)
const narrow = window.matchMedia('(max-width: 960px)'), modal = ref(narrow.matches)
const workspace = () => document.querySelector<HTMLElement>('#page-pets .workspace.split')!
let inert: HTMLElement[] = []
function sync() {
  inert.forEach(node => { node.inert = false }); inert = []
  workspace().classList.toggle('has-detail', showing.value)
  if (showing.value && modal.value) {
    inert = [...document.querySelectorAll<HTMLElement>('.sidebar, .topbar, #page-pets .content-panel, #pet-filters')]
    inert.forEach(node => { node.inert = true })
  }
}
function resize() {
  modal.value = narrow.matches; sync()
  if (showing.value && modal.value) inspector.value?.focusClose()
}
async function close(restore = true) {
  emit('close', restore); await nextTick(); sync()
  if (restore) (props.trigger?.isConnected ? props.trigger : document.querySelector<HTMLElement>('#pet-view button.active'))?.focus({ preventScroll: true })
}
function locate() { if (place.value) emit('locate', 'team_id' in place.value ? 0 : place.value.box_id) }
function keydown(event: KeyboardEvent) {
  if (!showing.value) return
  if (event.key === 'Escape') { event.preventDefault(); event.stopImmediatePropagation(); void close() }
  if (modal.value && event.key === 'Tab') {
    const root = inspector.value?.el
    if (!root) return
    const nodes = [...root.querySelectorAll<HTMLElement>('button:not([disabled]), input, select, summary, [tabindex="0"]')].filter(node => node.getClientRects().length > 0)
    if (!nodes.length) return
    const first = nodes[0]!, last = nodes.at(-1)!
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
  }
}
watch(showing, value => { sync(); if (value) void nextTick(() => inspector.value?.focusClose()) }, { flush: 'sync' })
watch(() => pet.value?.gid, (gid, previous) => { if (gid !== previous) void nextTick(() => { const body = inspector.value?.body; if (body) body.scrollTop = 0 }) })
watch(() => [showing.value, pet.value?.gid, props.model.data.value?.version] as const, ([visible, gid]) => {
  if (visible && gid !== undefined) void props.model.loadDetail(gid)
})
watch(() => props.model.selected.value, value => { if (value === null && props.open) emit('close', false) })
onMounted(() => { narrow.addEventListener('change', resize); document.addEventListener('keydown', keydown, true) })
onUnmounted(() => { inert.forEach(node => { node.inert = false }); workspace().classList.remove('has-detail'); narrow.removeEventListener('change', resize); document.removeEventListener('keydown', keydown, true) })
</script>
<template>
  <Teleport to="#pet-detail-root">
    <div v-if="showing && modal" class="detail-backdrop" data-vue-page @click="close()"></div>
    <PageInspector
      v-if="showing && pet"
      id="pet-detail"
      ref="inspector"
      title="精灵详情"
      :meta="panelPet ? '#' + String(panelPet.gid).padStart(4, '0') : undefined"
      :modal="modal"
      storage-key="pets"
      :default-width="360"
      :resizable="false"
      :aria-busy="model.detailBusy.value || undefined"
      @close="close()"
    >
      <template #actions>
        <button v-if="place" type="button" class="ghost-button small" :aria-label="'team_id' in place ? '定位到出战背包' : '定位到此箱'" :data-locate-team="'team_id' in place ? place.team_id : undefined" :data-locate-box="'box_id' in place ? place.box_id : undefined" @click="locate">{{ 'team_id' in place ? '定位到出战背包' : '定位到此箱' }}</button>
      </template>
      <div v-if="detailedPet" class="pet-detail-content" :class="{ 'is-refreshing': !detailIsCurrent || model.detailBusy.value }">
        <PetDetail :pet="detailedPet" :boxes="model.data.value!.backpack.boxes" @locate="emit('locate', $event)" />
        <div v-if="!detailIsCurrent || model.detailBusy.value" class="pet-detail-refresh" role="status">
          {{ model.detailBusy.value ? '正在更新详情…' : model.detailError.value || '详情暂不可用' }}
        </div>
      </div>
      <p v-else-if="model.detailBusy.value" class="filter-note pet-detail-placeholder" role="status">正在加载详情…</p>
      <div v-else class="filter-note pet-detail-placeholder" role="status">
        <p>{{ model.detailError.value || '详情暂不可用' }}</p>
        <button type="button" class="ghost-button small" @click="model.loadDetail(pet!.gid)">重试</button>
      </div>
    </PageInspector>
  </Teleport>
</template>
