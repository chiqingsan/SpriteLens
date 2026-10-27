<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import UiIcon from './UiIcon.vue'

const props = defineProps<{ modelValue: string | number; options: { value: string | number; label: string }[]; disabled?: boolean; label: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: any]; change: [value: any] }>()
const root = ref<HTMLElement | null>(null)
const open = ref(false)
const selected = computed(() => props.options.find(option => option.value === props.modelValue)?.label || '')
function choose(value: string | number) {
  open.value = false
  if (value !== props.modelValue) { emit('update:modelValue', value); emit('change', value) }
  root.value?.querySelector('button')?.focus()
}
function navigate(event: KeyboardEvent) {
  if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key) || !props.options.length) return
  event.preventDefault()
  if (!open.value) {
    open.value = true
    void nextTick(() => root.value?.querySelector<HTMLElement>('[aria-selected="true"]')?.focus())
    return
  }
  const buttons = [...(root.value?.querySelectorAll<HTMLButtonElement>('[role=option]') || [])]
  const current = buttons.indexOf(document.activeElement as HTMLButtonElement)
  const index = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1
    : Math.max(0, Math.min(buttons.length - 1, current + (event.key === 'ArrowDown' ? 1 : -1)))
  buttons[index]?.focus()
}
function focusOut(event: FocusEvent) { if (!root.value?.contains(event.relatedTarget as Node | null)) open.value = false }
function outside(event: MouseEvent) { if (!root.value?.contains(event.target as Node)) open.value = false }
onMounted(() => document.addEventListener('click', outside))
onBeforeUnmount(() => document.removeEventListener('click', outside))
</script>
<template>
  <span ref="root" class="ui-custom-select" @keydown="navigate" @keydown.esc.stop="open = false; root?.querySelector('button')?.focus()" @focusout="focusOut">
    <button type="button" class="ui-select-trigger" :disabled="disabled" :aria-label="label" :aria-expanded="open" aria-haspopup="listbox" @click="open = !open">
      <span>{{ selected }}</span><UiIcon name="chevron-down" />
    </button>
    <span v-if="open" class="ui-select-menu" role="listbox" :aria-label="label">
      <button v-for="option in options" :key="option.value" type="button" role="option" :aria-selected="option.value === modelValue" @click="choose(option.value)">{{ option.label }}</button>
    </span>
  </span>
</template>
<style>
.ui-custom-select { display: inline-flex; position: relative; min-width: 0; }
.ui-select-trigger { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); width: 100%; min-width: 0; min-height: 32px; padding: 0 var(--space-3); border: 1px solid var(--hairline); border-radius: var(--radius-sm); background: var(--field-bg); color: var(--ink); box-shadow: var(--field-inset); cursor: pointer; }
.ui-select-trigger > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ui-select-trigger .ui-icon { width: 16px; height: 16px; flex: none; color: var(--muted); }
.ui-select-trigger:focus-visible { outline: 2px solid var(--teal); outline-offset: 2px; }
.ui-select-trigger:disabled { opacity: .5; cursor: default; }
.ui-select-menu { position: absolute; z-index: 100; top: calc(100% + 4px); left: 0; min-width: 100%; width: max-content; max-width: min(320px, 90vw); max-height: min(280px, 50vh); overflow-y: auto; padding: 4px; border: 1px solid var(--hairline); border-radius: var(--radius-sm); background: var(--field-bg); box-shadow: 0 6px 20px #0002; }
.ui-select-menu button { display: block; width: 100%; padding: 7px 10px; border: 0; border-radius: var(--radius-sm); background: transparent; color: var(--ink); text-align: left; overflow-wrap: anywhere; cursor: pointer; }
.ui-select-menu button:hover, .ui-select-menu button:focus-visible, .ui-select-menu button[aria-selected="true"] { background: var(--focus-halo); }
</style>
