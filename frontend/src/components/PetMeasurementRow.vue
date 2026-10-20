<script setup lang="ts">
import { computed } from 'vue'
import type { PetMeasurement } from '../types/pets'
const props = defineProps<{ field: 'height' | 'weight' | 'voice'; measurement: PetMeasurement; limits: [number, number] | null; referenceOnly: boolean }>()
const title = computed(() => ({ height: '身高', weight: '体重', voice: '声音' }[props.field]))
const unit = computed(() => ({ height: 'm', weight: 'kg', voice: 'dB' }[props.field]))
function format(value: number) { return String(Number(value.toFixed(props.field === 'weight' ? 3 : props.field === 'height' ? 2 : 0))).replace('-', '−') }
const value = computed(() => props.referenceOnly ? props.limits ? `${format(props.limits[0])}–${format(props.limits[1])}${unit.value}` : '范围未采集' : props.measurement.value === null ? '未确认' : format(props.measurement.value) + unit.value)
const percentage = computed(() => props.referenceOnly || props.measurement.ratio === null ? '' : props.measurement.status !== 'within' ? '超界' : String(Number((props.measurement.ratio * 100).toFixed(2))) + '%')
const marker = computed(() => Math.max(0, Math.min(1, props.measurement.ratio || 0)) * 100 + '%')
const hasProgress = computed(() => !props.referenceOnly && props.measurement.ratio !== null)
</script>
<template>
  <section class="detail-measurement" :class="'measure-' + field"><header><span>{{ title }} <b>{{ value }}</b></span><strong>{{ percentage }}</strong></header><div v-if="limits" class="detail-measurement-scale"><span>{{ format(limits[0]) }}{{ unit }}</span><div class="detail-range-track" :class="{ 'has-progress': hasProgress }" :role="hasProgress ? 'progressbar' : undefined" :aria-valuemin="hasProgress ? 0 : undefined" :aria-valuemax="hasProgress ? 100 : undefined" :aria-valuenow="hasProgress ? Math.round((measurement.ratio || 0) * 100) : undefined"><span v-if="hasProgress" class="detail-range-fill" :style="{ width: marker }"></span><b v-if="hasProgress" :style="{ left: marker }"></b></div><span>{{ format(limits[1]) }}{{ unit }}</span></div><p v-else class="filter-note">暂无范围资料</p><small v-if="field === 'weight' && limits && !referenceOnly">体型参考：小不点 ≤{{ format(limits[0] + (limits[1] - limits[0]) * .02) }}kg · 大块头 ≥{{ format(limits[1] - (limits[1] - limits[0]) * .02) }}kg</small><small v-if="field === 'voice'">声音参考：粗嗓门 &lt;−95dB · 婉转声 &gt;95dB</small></section>
</template>
