<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import UiIcon from './UiIcon.vue'

const props = withDefaults(defineProps<{
  title: string
  meta?: string
  modal?: boolean
  storageKey?: string
  defaultWidth?: number
  minWidth?: number
  maxWidth?: number
}>(), { modal: false, storageKey: '', defaultWidth: 360, minWidth: 280, maxWidth: 560 })

const emit = defineEmits<{ (e: 'close'): void }>()

const el = ref<HTMLElement>()
const body = ref<HTMLElement>()
const closeButton = ref<HTMLButtonElement>()
const WIDTH_KEY = 'sn.inspector.'

function loadWidth() {
  if (!props.storageKey) return props.defaultWidth
  const raw = Number(localStorage.getItem(WIDTH_KEY + props.storageKey))
  return Number.isFinite(raw) && raw > 0 ? clamp(raw) : props.defaultWidth
}
function clamp(value: number) {
  return Math.min(props.maxWidth, Math.max(props.minWidth, Math.round(value)))
}
function storeWidth() {
  if (props.storageKey) localStorage.setItem(WIDTH_KEY + props.storageKey, String(width.value))
}

const width = ref(loadWidth())
const resizing = ref(false)
let startX = 0
let startWidth = 0

function startResize(event: PointerEvent) {
  if (props.modal || event.button !== 0) return
  event.preventDefault()
  resizing.value = true
  startX = event.clientX
  startWidth = width.value
  document.body.classList.add('ui-resizing')
  window.addEventListener('pointermove', onResize)
  window.addEventListener('pointerup', stopResize, { once: true })
}
function onResize(event: PointerEvent) {
  width.value = clamp(startWidth + (startX - event.clientX))
}
function stopResize() {
  if (!resizing.value) return
  resizing.value = false
  document.body.classList.remove('ui-resizing')
  window.removeEventListener('pointermove', onResize)
  storeWidth()
}
function resetWidth() {
  width.value = props.defaultWidth
  if (props.storageKey) localStorage.removeItem(WIDTH_KEY + props.storageKey)
}
function nudgeWidth(delta: number) {
  width.value = clamp(width.value + delta)
  storeWidth()
}
function onHandleKeydown(event: KeyboardEvent) {
  if (event.key === 'ArrowLeft') { event.preventDefault(); nudgeWidth(16) }
  else if (event.key === 'ArrowRight') { event.preventDefault(); nudgeWidth(-16) }
  else if (event.key === 'Home') { event.preventDefault(); resetWidth() }
}
onBeforeUnmount(() => {
  window.removeEventListener('pointermove', onResize)
  document.body.classList.remove('ui-resizing')
})

defineExpose({ el, body, focusClose: () => closeButton.value?.focus({ preventScroll: true }) })
</script>

<template>
  <aside
    ref="el"
    class="ui-inspector"
    :class="{ 'is-modal': modal, 'is-resizing': resizing }"
    :style="modal ? undefined : { width: `${width}px` }"
    :role="modal ? 'dialog' : 'region'"
    :aria-modal="modal || undefined"
    :aria-label="title"
  >
    <span
      v-if="!modal"
      class="ui-inspector-handle"
      role="separator"
      aria-orientation="vertical"
      :aria-valuenow="width"
      :aria-valuemin="minWidth"
      :aria-valuemax="maxWidth"
      aria-label="拖动调整详情宽度"
      tabindex="0"
      title="拖动调整宽度，双击恢复默认"
      @pointerdown="startResize"
      @dblclick="resetWidth"
      @keydown="onHandleKeydown"
    ></span>
    <header class="ui-inspector-head">
      <h2 class="ui-inspector-title">{{ title }}<small v-if="meta">{{ meta }}</small></h2>
      <div class="ui-inspector-actions">
        <slot name="actions" />
        <button ref="closeButton" type="button" class="ui-inspector-close" aria-label="关闭详情" title="关闭详情" @click="emit('close')">
          <UiIcon name="x" />
        </button>
      </div>
    </header>
    <div ref="body" class="ui-inspector-body">
      <slot />
    </div>
  </aside>
</template>

<style>
.ui-inspector {
  position: relative;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-lg);
  background: var(--panel);
  overflow: hidden;
}

.ui-inspector-handle {
  position: absolute;
  inset: 0 auto 0 0;
  z-index: 4;
  width: 6px;
  cursor: col-resize;
  touch-action: none;
}

.ui-inspector-handle:hover,
.ui-inspector.is-resizing .ui-inspector-handle {
  background: color-mix(in srgb, var(--teal) 22%, transparent);
}

.ui-inspector-handle:focus-visible {
  outline: 2px solid var(--focus-ring);
  outline-offset: -2px;
}

body.ui-resizing {
  user-select: none;
  cursor: col-resize;
}

.ui-inspector-head {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--line-soft);
  background: var(--panel);
}

.ui-inspector-title {
  margin: 0;
  display: inline-flex;
  align-items: baseline;
  gap: var(--space-2);
  min-width: 0;
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--ink);
  white-space: nowrap;
}

.ui-inspector-title small {
  overflow: hidden;
  font-size: var(--fs-3xs);
  font-weight: 400;
  color: var(--muted);
  text-overflow: ellipsis;
}

.ui-inspector-actions {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  flex: none;
}

.ui-inspector-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  padding: 0;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--muted);
}

.ui-inspector-close:hover {
  border-color: var(--hairline);
  background: var(--surface-2);
  color: var(--ink);
}

.ui-inspector-close:focus-visible {
  outline: 2px solid var(--focus-ring);
  outline-offset: 1px;
}

.ui-inspector-body {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  overscroll-behavior: contain;
  padding: var(--space-3) var(--space-4) var(--space-4);
}

.ui-inspector.is-modal {
  position: fixed;
  inset: 0 0 0 auto;
  z-index: 120;
  width: min(420px, 100vw);
  border: 0;
  border-left: 1px solid var(--line);
  border-radius: 0;
  box-shadow: var(--shadow-pop);
  animation: ui-inspector-in 200ms var(--motion-ease) both;
}

.desktop-window .ui-inspector.is-modal {
  top: var(--window-titlebar, 0px);
}

@keyframes ui-inspector-in {
  from { opacity: 0; transform: translateX(18px); }
  to { opacity: 1; transform: none; }
}

@media (prefers-reduced-motion: reduce) {
  .ui-inspector.is-modal { animation: none; }
}
</style>
