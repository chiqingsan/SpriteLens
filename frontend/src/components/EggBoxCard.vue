<script setup lang="ts">
import type { EggBoxEntry } from '../types/eggBox'
import EggBoxArtwork from './EggBoxArtwork.vue'
import UiIcon from './UiIcon.vue'

defineProps<{ egg: EggBoxEntry; selected: boolean }>()
const emit = defineEmits<{ select: [egg: EggBoxEntry, event: MouseEvent] }>()

function height(value: number) { return value > 0 ? `${(value / 100).toFixed(2)}m` : '—' }
function weight(value: number) { return value > 0 ? `${(value / 1000).toFixed(3)}kg` : '—' }
function date(value: number) {
  return value > 0 ? new Date(value * 1000).toLocaleString('sv-SE', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }) : '获得时间未知'
}
</script>

<template>
  <button type="button" class="eggbox-card" :class="{ selected }" :data-egg-instance="egg.instance_id" :aria-pressed="selected" :aria-label="`${egg.egg_name}，编号${egg.instance_id}`" @click="emit('select', egg, $event)">
    <span v-if="egg.hatching" class="eggbox-card-status">孵化中 {{ Math.round(egg.hatch_progress * 100) }}%</span>
    <span v-if="egg.quantity > 1" class="eggbox-card-quantity">×{{ egg.quantity }}</span>
    <div class="eggbox-card-heading">
      <EggBoxArtwork :egg="egg" size="card" />
      <strong class="eggbox-card-name" :title="egg.egg_name">{{ egg.egg_name }}</strong>
    </div>
    <div class="eggbox-card-foot">
      <div class="eggbox-card-measures">
        <span :title="`尺寸 ${height(egg.height_cm)}`"><UiIcon name="ruler-2" /><span class="sr-only">尺寸</span>{{ height(egg.height_cm) }}</span>
        <span :title="`重量 ${weight(egg.weight_g)}`"><UiIcon name="weight" /><span class="sr-only">重量</span>{{ weight(egg.weight_g) }}</span>
      </div>
      <time :datetime="egg.obtained_at > 0 ? new Date(egg.obtained_at * 1000).toISOString() : undefined"><UiIcon name="clock" />{{ date(egg.obtained_at) }}</time>
    </div>
  </button>
</template>
