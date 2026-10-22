<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useId, watch } from 'vue'
import UiIcon from './UiIcon.vue'
const props = defineProps<{ label: string; options: { value: string; label: string; iconUrl?: string }[]; modelValue: string[]; multiple?: boolean; mode?: 'union' | 'intersection'; active: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: string[]]; 'update:mode': [value: 'union' | 'intersection'] }>()
const dialog = ref<HTMLDialogElement>()
const headingId = useId()
function choose(value: string) {
  const selected = !value ? [] : props.multiple
    ? props.modelValue.includes(value) ? props.modelValue.filter(entry => entry !== value) : [...props.modelValue, value]
    : [value]
  emit('update:modelValue', selected)
  if (!props.multiple) dialog.value?.close()
}
function isSelected(value: string) { return value ? props.modelValue.includes(value) : !props.modelValue.length }
const selectionSummary = computed(() => props.modelValue.length
  ? props.modelValue.map(value => props.options.find(option => option.value === value)?.label || value).join(props.mode === 'intersection' ? ' AND ' : ' OR ')
  : props.options[0]?.label || '全部')
watch(() => props.active, value => { if (!value) dialog.value?.close() })
onBeforeUnmount(() => dialog.value?.close())
</script>
<template>
  <button class="dex-filter-button" :class="{ active: modelValue.length }" aria-haspopup="dialog" @click="dialog?.showModal()"><small>{{ label }}</small><b>{{ selectionSummary }}</b><UiIcon name="chevron-down" /></button>
  <dialog ref="dialog" class="dex-filter-dialog" :aria-labelledby="headingId" @click.self="dialog?.close()">
    <header><div class="dex-dialog-heading"><h3 :id="headingId">按{{ label }}筛选</h3><div v-if="multiple" class="dex-group-mode" aria-label="蛋组匹配方式"><button type="button" :aria-pressed="mode !== 'intersection'" aria-label="OR，满足任一蛋组" @click="emit('update:mode', 'union')">OR</button><button type="button" :aria-pressed="mode === 'intersection'" aria-label="AND，同时满足蛋组" @click="emit('update:mode', 'intersection')">AND</button></div></div><button class="ghost-button small" aria-label="关闭筛选" @click="dialog?.close()"><UiIcon name="x" /></button></header>
    <p>{{ multiple ? '可多选，选择后立即更新图鉴结果' : '选择后立即更新图鉴结果' }}</p>
    <div class="dex-filter-options"><button v-for="option in options" :key="option.value" :aria-pressed="isSelected(option.value)" @click="choose(option.value)"><span class="dex-filter-option-label"><img v-if="option.iconUrl" :src="option.iconUrl" :alt="`${option.label}系别图标`" loading="lazy" decoding="async"><span>{{ option.label }}</span></span><UiIcon name="circle-check" :class="{ 'is-hidden': !isSelected(option.value) }" /></button></div>
  </dialog>
</template>
