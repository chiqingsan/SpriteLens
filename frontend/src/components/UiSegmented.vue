<script setup lang="ts">
import { onBeforeUnmount, onMounted, onUpdated, ref } from 'vue'

const props = defineProps<{ navigation?: boolean }>()
const root = ref<HTMLElement | null>(null)
const indicator = ref<HTMLElement | null>(null)
const ready = ref(false)
let observer: ResizeObserver | null = null
let readyFrame = 0
let navigationTimer: ReturnType<typeof setTimeout> | undefined
let finishNavigation: ((event?: TransitionEvent) => void) | undefined
let navigating = false
function moveTo(button: HTMLElement | null | undefined) {
  if (!button || !indicator.value) return
  indicator.value.style.width = `${button.offsetWidth}px`
  indicator.value.style.transform = `translateX(${button.offsetLeft}px)`
}
function position() {
  if (!root.value?.getClientRects().length) return
  if (props.navigation && finishNavigation) return
  if (props.navigation) root.value.classList.remove('is-sliding')
  moveTo(root.value.querySelector<HTMLElement>(':scope > button.active'))
}
function navigate(event: MouseEvent) {
  if (!props.navigation || navigating || matchMedia('(prefers-reduced-motion: reduce)').matches) return
  const button = (event.target as HTMLElement).closest<HTMLButtonElement>('button[data-goto-page]')
  if (!button) return
  if (finishNavigation) indicator.value!.removeEventListener('transitionend', finishNavigation)
  clearTimeout(navigationTimer)
  finishNavigation = undefined
  navigationTimer = undefined
  if (button.classList.contains('active')) { position(); return }
  event.stopPropagation()
  const active = root.value!.querySelector<HTMLElement>(':scope > button.active')!
  const previousWidth = active.offsetWidth, previousLeft = active.offsetLeft
  root.value!.classList.add('is-sliding')
  finishNavigation = (transitionEvent?: TransitionEvent) => {
    if (transitionEvent && (transitionEvent.target !== indicator.value || transitionEvent.propertyName !== 'transform')) return
    indicator.value!.removeEventListener('transitionend', finishNavigation!)
    clearTimeout(navigationTimer)
    navigationTimer = undefined; finishNavigation = undefined
    if (root.value!.getClientRects().length) { navigating = true; button.click(); navigating = false }
    root.value!.classList.remove('is-sliding')
    indicator.value!.style.width = `${previousWidth}px`
    indicator.value!.style.transform = `translateX(${previousLeft}px)`
  }
  indicator.value!.addEventListener('transitionend', finishNavigation)
  moveTo(button)
  navigationTimer = setTimeout(() => finishNavigation?.(), 500)
}
onMounted(() => {
  position()
  readyFrame = requestAnimationFrame(() => { ready.value = true })
  if (typeof ResizeObserver === 'undefined' || !root.value) return
  observer = new ResizeObserver(position)
  observer.observe(root.value)
  root.value.querySelectorAll('button').forEach(button => observer!.observe(button))
})
onUpdated(position)
onBeforeUnmount(() => { observer?.disconnect(); if (finishNavigation) indicator.value?.removeEventListener('transitionend', finishNavigation); clearTimeout(navigationTimer); cancelAnimationFrame(readyFrame) })
</script>

<template>
  <div ref="root" class="segmented ui-sliding-segmented" :class="{ 'is-ready': ready, 'ui-navigation': navigation }" @click.capture="navigate"><slot /><span ref="indicator" class="ui-segment-indicator" aria-hidden="true"></span></div>
</template>

<style>
.ui-sliding-segmented { position: relative; isolation: isolate; }
.ui-sliding-segmented > .ui-segment-indicator {
  position: absolute; z-index: -1; top: 2px; bottom: 2px; left: 0;
  border-radius: calc(var(--radius-md) - 2px); background: var(--panel); box-shadow: var(--shadow-1);
  pointer-events: none;
}
.ui-sliding-segmented.is-ready:not(.ui-navigation) > .ui-segment-indicator { transition: transform var(--motion-base) var(--motion-ease), width var(--motion-base) var(--motion-ease); }
.ui-sliding-segmented.ui-navigation.is-sliding > .ui-segment-indicator { transition: transform var(--motion-fast) var(--motion-ease), width var(--motion-fast) var(--motion-ease); }
.segmented.ui-sliding-segmented > button.active { background: transparent; box-shadow: none; }
</style>
