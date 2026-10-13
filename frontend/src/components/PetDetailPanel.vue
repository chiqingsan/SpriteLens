<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import type { PetsModel } from '../composables/usePets'
import PetDetail from './PetDetail.vue'
import UiIcon from './UiIcon.vue'
const props = defineProps<{ model: PetsModel; open: boolean; enabled: boolean; trigger: HTMLElement | null; visibleGids: number[]; imageMode: string }>()
const emit = defineEmits<{ close: [restore?: boolean]; select: [gid: number, element: HTMLElement | null]; locate: [id: number] }>()
const pet = computed(() => props.model.selected.value === null ? null : props.model.find(props.model.selected.value))
const showing = computed(() => props.open && props.enabled && !!pet.value)
const panel = ref<HTMLElement>(), closeButton = ref<HTMLButtonElement>()
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
const index = computed(() => props.visibleGids.indexOf(props.model.selected.value!))
function navigate(step: number) {
  const gid = props.visibleGids[index.value + step]
  if (gid !== undefined) emit('select', gid, document.querySelector<HTMLElement>(`#page-pets [data-gid="${gid}"]`))
}
function keydown(event: KeyboardEvent) {
  if (!showing.value) return
  if (event.key === 'Escape') { event.preventDefault(); event.stopImmediatePropagation(); void close() }
  if (modal.value && event.key === 'Tab') {
    const nodes = [...panel.value!.querySelectorAll<HTMLElement>('button:not([disabled]), input, select, [tabindex="0"]')]
    const first = nodes[0]!, last = nodes.at(-1)!
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
  }
}
watch(showing, value => { sync(); if (value) void nextTick(() => closeButton.value?.focus({ preventScroll: true })) }, { flush: 'sync' })
onMounted(() => { narrow.addEventListener('change', resize); document.addEventListener('keydown', keydown, true) })
onUnmounted(() => { inert.forEach(node => { node.inert = false }); workspace().classList.remove('has-detail'); narrow.removeEventListener('change', resize); document.removeEventListener('keydown', keydown, true) })
</script>
<template>
  <Teleport to="#pet-detail-root">
<div v-if="showing && modal" class="detail-backdrop" data-vue-page @click="close()"></div><aside v-if="showing && pet" id="pet-detail" ref="panel" class="detail-panel detail-open" data-vue-page :role="modal ? 'dialog' : 'region'" :aria-modal="modal || undefined" :aria-label="pet.name + '详情'">
    <button ref="closeButton" type="button" class="ghost-button small detail-close" @click="close()"><UiIcon name="x"></UiIcon>关闭详情</button>
    <div class="detail-navigation"><button class="ghost-button small" :disabled="index <= 0" @click="navigate(-1)"><UiIcon name="chevron-left"></UiIcon>上一只</button><button class="ghost-button small" :disabled="index < 0 || index >= visibleGids.length - 1" @click="navigate(1)"><UiIcon name="chevron-right"></UiIcon>下一只</button></div>
    <PetDetail :pet="pet" :boxes="model.data.value!.backpack.boxes" :image-mode="imageMode" @locate="emit('locate', $event)"></PetDetail>
  </aside>
</Teleport>
</template>
