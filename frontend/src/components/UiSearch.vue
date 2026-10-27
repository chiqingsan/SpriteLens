<script setup lang="ts">
import { computed, ref } from 'vue'
import UiIcon from './UiIcon.vue'

/* 统一搜索框：边框 / 底色 / 焦点光晕由外层容器承载，内部 input 全面复位。
   原生 input[type=search] 的外观（WebView2 旧版会自绘白底描边与清除叉）一律关闭，
   清空按钮由组件自己渲染，并在无内容时保留占位，避免输入时整条工具栏宽度跳动。 */
const props = withDefaults(defineProps<{
  modelValue: string
  label?: string
  placeholder?: string
  id?: string
  disabled?: boolean
  compact?: boolean
  clearable?: boolean
}>(), {
  label: '搜索', placeholder: '', id: undefined, disabled: false, compact: false, clearable: true,
})
const emit = defineEmits<{
  (event: 'update:modelValue', value: string): void
  (event: 'search', value: string): void
}>()

const input = ref<HTMLInputElement>()
const hasValue = computed(() => props.modelValue.length > 0)

function onInput(event: Event) {
  emit('update:modelValue', (event.target as HTMLInputElement).value)
}

function clear() {
  emit('update:modelValue', '')
  input.value?.focus()
}

function focus() {
  input.value?.focus()
}

defineExpose({ focus })
</script>

<template>
  <div class="ui-search" :class="{ 'ui-search--compact': compact, 'is-disabled': disabled }">
    <UiIcon name="search" class="ui-search__icon" />
    <input
      :id="id" ref="input" class="ui-search__input" type="search"
      :value="modelValue" :placeholder="placeholder" :aria-label="label"
      :disabled="disabled" autocomplete="off" spellcheck="false"
      @input="onInput" @keydown.enter="emit('search', modelValue)">
    <button
      v-if="clearable" type="button" class="ui-search__clear" :class="{ 'is-hidden': !hasValue }"
      :disabled="disabled" :aria-label="`清空${label}`" @click="clear">
      <UiIcon name="x" />
    </button>
  </div>
</template>
