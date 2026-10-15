<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import type { PetsModel } from '../composables/usePets'
import PetDetail from './PetDetail.vue'
import './pet-detail.css'
const props = defineProps<{ model: PetsModel; open: boolean; enabled: boolean; trigger: HTMLElement | null; imageMode: string }>()
const emit = defineEmits<{ close: [restore?: boolean]; locate: [id: number] }>()
const pet = computed(() => props.model.selected.value === null ? null : props.model.find(props.model.selected.value))
const detailedPet = computed(() => {
  const loaded = props.model.detail.value
  return loaded && loaded.gid === pet.value?.gid && loaded.uid === props.model.data.value?.uid
    && loaded.version >= props.model.data.value?.version ? loaded.pet : null
})
const place = computed(() => pet.value?.location ?? null)
const showing = computed(() => props.open && props.enabled && !!pet.value)
const panel = ref<HTMLElement>(), closeButton = ref<HTMLButtonElement>(), body = ref<HTMLElement>()
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
function resize() { modal.value = narrow.matches; sync(); if (showing.value && modal.value) closeButton.value?.focus() }
async function close(restore = true) {
  emit('close', restore); await nextTick(); sync()
  if (restore) (props.trigger?.isConnected ? props.trigger : document.querySelector<HTMLElement>('#pet-view button.active'))?.focus({ preventScroll: true })
}
function locate() { if (place.value) emit('locate', 'team_id' in place.value ? 0 : place.value.box_id) }
function keydown(event: KeyboardEvent) {
  if (!showing.value) return
  if (event.key === 'Escape') { event.preventDefault(); event.stopImmediatePropagation(); void close() }
  if (modal.value && event.key === 'Tab') {
    const nodes = [...panel.value!.querySelectorAll<HTMLElement>('button:not([disabled]), input, select, summary, [tabindex="0"]')].filter(node => node.getClientRects().length > 0)
    const first = nodes[0]!, last = nodes.at(-1)!
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
  }
}
watch(showing, value => { sync(); if (value) void nextTick(() => closeButton.value?.focus({ preventScroll: true })) }, { flush: 'sync' })
watch(() => pet.value?.gid, (gid, previous) => { if (gid !== previous) void nextTick(() => { if (body.value) body.value.scrollTop = 0 }) })
watch(() => [showing.value, pet.value?.gid, props.model.data.value?.version] as const, ([visible, gid]) => {
  if (visible && gid !== undefined) void props.model.loadDetail(gid)
})
watch(() => props.model.selected.value, value => { if (value === null && props.open) emit('close', false) })
onMounted(() => { narrow.addEventListener('change', resize); document.addEventListener('keydown', keydown, true) })
onUnmounted(() => { inert.forEach(node => { node.inert = false }); workspace().classList.remove('has-detail'); narrow.removeEventListener('change', resize); document.removeEventListener('keydown', keydown, true) })
</script>
<template>
  <Teleport to="#pet-detail-root">
<div v-if="showing && modal" class="detail-backdrop" data-vue-page @click="close()"></div><aside v-if="showing && pet" id="pet-detail" ref="panel" class="detail-panel detail-open" data-vue-page :role="modal ? 'dialog' : 'region'" :aria-modal="modal || undefined" :aria-label="pet.name + '详情'">
    <header class="pet-detail-toolbar"><h2>精灵详情</h2><div><button v-if="place" type="button" class="ghost-button small" :aria-label="'team_id' in place ? '定位到出战背包' : '定位到此箱'" :data-locate-team="'team_id' in place ? place.team_id : undefined" :data-locate-box="'box_id' in place ? place.box_id : undefined" @click="locate">{{ 'team_id' in place ? '定位到出战背包' : '定位到此箱' }}</button><button ref="closeButton" type="button" class="ghost-button small" aria-label="关闭详情" @click="close()">关闭</button></div></header>
    <div ref="body" class="pet-detail-body">
      <PetDetail v-if="detailedPet" :pet="detailedPet" :boxes="model.data.value!.backpack.boxes" @locate="emit('locate', $event)" />
      <p v-else-if="model.detailBusy.value" class="filter-note">正在加载详情…</p>
      <div v-else class="filter-note" role="status">
        <p>{{ model.detailError.value || '详情暂不可用' }}</p>
        <button type="button" class="ghost-button small" @click="model.loadDetail(pet!.gid)">重试</button>
      </div>
    </div>
  </aside>
</Teleport>
</template>
