<script setup lang="ts">
import { measures, type PetAdvancedModel } from '../composables/usePetAdvancedFilters'
import type { PetFilterModel } from '../composables/usePetFilters'
import DualRangeSlider from './DualRangeSlider.vue'
const { model, basic } = defineProps<{ model: PetAdvancedModel; basic: PetFilterModel }>()
const { filters, status, groups } = model
function limits(field: typeof measures[number][0]) {
  return field === 'voice' ? basic.options.value.measurement_limits.voice : { min: 0, max: 100 }
}
function summary(kind: 'voice' | 'height' | 'weight') {
  const values = measures.filter(([field]) => field.startsWith(kind) && (filters[`${field}_min`] !== null || filters[`${field}_max`] !== null))
    .map(([field, , unit]) => {
      const low = filters[`${field}_min`] ?? limits(field).min, high = filters[`${field}_max`] ?? limits(field).max
      return low === high ? `${low}${unit}` : `${low}–${high}${unit}`
    })
  return values.join(' · ') || '不限'
}
</script>
<template>
  <details class="filter-section" style="order: 5">
<summary>蛋组 <small data-filter-summary="egg_groups" :title="filters.egg_groups.join('、')">{{ filters.egg_groups.join('、') || '不限' }}</small></summary>

    <div id="f-egg-groups" class="chip-group"><button v-for="group in groups" :key="group" class="chip" :class="{ active: filters.egg_groups.includes(group) }" :aria-pressed="filters.egg_groups.includes(group)" @click="model.group(group)">{{ group }}</button></div>
    <button v-if="filters.egg_groups.length" class="text-button filter-clear" @click="model.patch({ egg_groups: [] })">清除蛋组</button>
  </details>
  <details v-for="[kind, label, order] in ([['voice', '声音', 9], ['height', '身高', 10], ['weight', '体重', 11]] as const)" :key="kind" class="filter-section" :style="{ order }">
    <summary>{{ label }}<small :title="summary(kind)">{{ summary(kind) }}</small></summary>
    <div v-for="[field, title, unit, step] in measures.filter(([field]) => field.startsWith(kind))" :key="field" class="measurement-slider">
      <DualRangeSlider :field="field" :label="title" :unit="unit" :step="Number(step)" :min="limits(field).min" :max="limits(field).max" :low="filters[`${field}_min`]" :high="filters[`${field}_max`]" @input="(bound, value, commit, min, max) => model.range(field, bound, value, min, max, commit)"></DualRangeSlider>
    </div>
  </details>
  <p v-if="status" id="measurement-filter-status" class="filter-note" style="order: 13" role="status">{{ status }}</p>
</template>
