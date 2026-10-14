<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import type { Pet, EvolutionNode } from '../types/pets'
const { pet } = defineProps<{ pet: Pet }>()
const failed = reactive<Record<number, boolean>>({})
const root = ref<HTMLElement | null>(null)
let drag: { pointerId: number; startX: number; startScrollLeft: number; container: HTMLElement } | null = null
function pointerDown(event: PointerEvent) {
  const container = event.currentTarget as HTMLElement
  if (event.pointerType !== 'mouse' || event.button !== 0 || container.scrollWidth <= container.clientWidth) return
  event.preventDefault()
  container.setPointerCapture(event.pointerId)
  container.classList.add('dragging')
  drag = { pointerId: event.pointerId, startX: event.clientX, startScrollLeft: container.scrollLeft, container }
}
function pointerMove(event: PointerEvent) {
  if (!drag || drag.pointerId !== event.pointerId) return
  event.preventDefault()
  drag.container.scrollLeft = drag.startScrollLeft - (event.clientX - drag.startX)
}
function pointerEnd(event: PointerEvent) {
  if (!drag || drag.pointerId !== event.pointerId) return
  drag.container.classList.remove('dragging')
  drag = null
}
const paths = computed(() => {
  const { nodes, edges } = pet.detail.evolution
  const byId = new Map(nodes.map(node => [node.id, node]))
  const result: EvolutionNode[][] = []
  function visit(node: EvolutionNode, path: EvolutionNode[]) {
    const next = edges.filter(edge => edge[0] === node.id && !path.some(item => item.id === edge[1])).map(edge => byId.get(edge[1])!)
    const current = [...path, node]
    if (next.length) next.forEach(target => visit(target, current))
    else result.push(current)
  }
  nodes.filter(node => !edges.some(edge => edge[1] === node.id)).forEach(node => visit(node, []))
  return result
})
function keepCurrentVisible() {
  root.value?.querySelectorAll<HTMLElement>('.detail-evolution-path').forEach(container => {
    container.classList.toggle('is-scrollable', container.scrollWidth > container.clientWidth)
    const current = container.querySelector<HTMLElement>('figure.current')
    if (!current) return
    const figures = [...container.querySelectorAll('figure')]
    const currentIndex = figures.indexOf(current)
    const bounds = current.getBoundingClientRect()
    const viewport = container.getBoundingClientRect()
    const initialRight = bounds.right - viewport.left + container.scrollLeft
    if (currentIndex <= 1 && initialRight <= container.clientWidth) {
      container.scrollLeft = 0
    } else if (bounds.left < viewport.left) {
      container.scrollLeft -= viewport.left - bounds.left
    } else if (bounds.right > viewport.right) {
      container.scrollLeft += bounds.right - viewport.right
    }
  })
}
function syncCurrentPosition() { void nextTick(keepCurrentVisible) }
watch([() => pet.base_conf_id, paths], syncCurrentPosition)
onMounted(() => { keepCurrentVisible(); window.addEventListener('resize', keepCurrentVisible) })
onBeforeUnmount(() => window.removeEventListener('resize', keepCurrentVisible))
</script>
<template>
  <section ref="root" class="detail-evolution"><h3>进化关系</h3><p v-if="!paths.length" class="filter-note">暂无进化资料</p><div v-for="(path, index) in paths" :key="index" class="detail-evolution-path" tabindex="0" aria-label="精灵进化关系，可按住鼠标拖动横向滚动" @pointerdown="pointerDown" @pointermove="pointerMove" @pointerup="pointerEnd" @pointercancel="pointerEnd" @lostpointercapture="pointerEnd"><template v-for="(node, step) in path" :key="node.id"><span v-if="step" class="evolution-arrow" aria-label="进化为">→</span><figure :class="{ current: node.id === pet.base_conf_id }"><span class="evolution-avatar"><img v-if="node.portrait_url && !failed[node.id]" :src="node.portrait_url" alt="" draggable="false" @error="failed[node.id] = true"><span v-else>{{ node.name.slice(0, 1) }}</span></span><figcaption>No.{{ node.dex_no || '—' }} {{ node.name }}<small v-if="node.id === pet.base_conf_id">当前</small></figcaption></figure></template></div></section>
</template>
