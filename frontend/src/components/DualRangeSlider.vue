<script setup lang="ts">
import { computed, ref, watch } from 'vue'
const props = defineProps<{ field: string; label: string; min: number; max: number; step: number; low: number | null; high: number | null; unit?: string }>()
const emit = defineEmits<{ input: [bound: 'min' | 'max', value: number, commit: boolean, minimum: number, maximum: number] }>()
const held = ref<{ min: number; max: number } | null>(null)
const axis = ref({ min: props.min, max: props.max })
watch(() => [props.min, props.max, props.low, props.high] as const, ([min, max, low, high], previous) => {
  const reset = !previous || previous[0] !== min || previous[1] !== max || low === null && high === null
  axis.value = { min: Math.min(reset ? min : axis.value.min, min, low ?? min, high ?? min),
    max: Math.max(reset ? max : axis.value.max, max, low ?? max, high ?? max) }
}, { immediate: true })
// 旧快捷条件可能超出当前背包量程；显示它们原有的值，拖动期间固定量程。
const bounds = computed(() => held.value || axis.value)
const low = computed(() => props.low ?? bounds.value.min), high = computed(() => props.high ?? bounds.value.max)
function input(bound: 'min' | 'max', event: Event, commit = false) {
  emit('input', bound, Number((event.target as HTMLInputElement).value), commit, bounds.value.min, bounds.value.max)
  if (commit) held.value = null
}
</script>
<template>
  <div class="dual-range-control">
    <div class="dual-range" :data-overlap="low === high" :style="{ '--range-ratio': (low - bounds.min) / (bounds.max - bounds.min), '--range-low': (low - bounds.min) / (bounds.max - bounds.min) * 100 + '%', '--range-high': (high - bounds.min) / (bounds.max - bounds.min) * 100 + '%' }" role="group" :aria-label="label + '范围'">
      <span class="dual-range-track" aria-hidden="true"><span></span></span>
      <input v-for="bound in (['min', 'max'] as const)" :id="'f-' + field + '-' + bound" :key="bound" :class="{ 'range-front': bound === 'min' && low === bounds.max }" type="range" :min="bounds.min" :max="bounds.max" :step="step" :value="bound === 'min' ? low : high" :data-measure-filter="field + '_' + bound" :aria-label="(bound === 'min' ? '最低' : '最高') + label" :aria-valuetext="(bound === 'min' ? props.low : props.high) === null ? '不限' : (bound === 'min' ? low : high) + (unit || '')" @pointerdown="held = { ...bounds }" @pointercancel="held = null" @blur="held = null" @input="input(bound, $event)" @change="input(bound, $event, true)">
    </div>
    <div v-if="unit" class="dual-range-unit"><span>{{ low }}{{ unit }}</span><span>{{ high }}{{ unit }}</span></div>
  </div>
</template>
