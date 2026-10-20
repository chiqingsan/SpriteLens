<script setup lang="ts">
import { onBeforeUnmount, ref, useId, watch } from 'vue'
const props = defineProps<{ label: string; options: { value: string; label: string }[]; modelValue: string[]; multiple?: boolean; mode?: 'union' | 'intersection'; active: boolean }>()
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
watch(() => props.active, value => { if (!value) dialog.value?.close() })
onBeforeUnmount(() => dialog.value?.close())
</script>
<template>
  <button class="dex-filter-button" :class="{ active: modelValue.length }" aria-haspopup="dialog" @click="dialog?.showModal()"><small>{{ label }}</small><b>{{ modelValue.length ? modelValue.map(value => options.find(option => option.value === value)?.label || value).join(mode === 'intersection' ? ' ∩ ' : ' ∪ ') : options[0]?.label || '全部' }}</b><span>⌄</span></button>
  <dialog ref="dialog" class="dex-filter-dialog" :aria-labelledby="headingId" @click.self="dialog?.close()">
    <header><h3 :id="headingId">按{{ label }}筛选</h3><button class="ghost-button small" aria-label="关闭筛选" @click="dialog?.close()">✕</button></header>
    <p>{{ multiple ? '可多选，选择后立即更新图鉴结果' : '选择后立即更新图鉴结果' }}</p>
    <div v-if="multiple" class="dex-group-mode"><button :aria-pressed="mode !== 'intersection'" @click="emit('update:mode', 'union')">并集 · 满足任一蛋组</button><button :aria-pressed="mode === 'intersection'" @click="emit('update:mode', 'intersection')">交集 · 同时满足蛋组</button></div>
    <div class="dex-filter-options"><button v-for="option in options" :key="option.value" :aria-pressed="option.value ? modelValue.includes(option.value) : !modelValue.length" @click="choose(option.value)"><span>{{ option.label }}</span><i>{{ (option.value ? modelValue.includes(option.value) : !modelValue.length) ? '✓' : '+' }}</i></button></div>
  </dialog>
</template>
