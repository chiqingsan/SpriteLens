<script setup lang="ts">
import { computed } from 'vue'

type RangeKey = 'height' | 'weight' | 'voice'
type RangeEntry = {
  key: RangeKey
  label: string
  low: string
  high: string
  unit: string
  range: string
  span: string
  reference: string
}

const props = defineProps<{ ranges: { height: string; weight: string }; areas?: string[]; egg?: boolean }>()

function decimalPlaces(value: string) {
  return value.includes('.') ? value.split('.')[1].length : 0
}

function formatValue(value: string) {
  return value.replace(/^-/, '−')
}

function formatMetric(value: number, key: RangeKey) {
  const digits = key === 'weight' ? 3 : key === 'height' ? 2 : 0
  return String(Number(value.toFixed(digits))).replace('-', '−')
}

function parseRange(key: RangeKey, label: string, value: string): RangeEntry | null {
  const match = value.trim().match(/^(-?[0-9]+(?:\.[0-9]+)?)\s*(?:-|–|—|~|至)\s*(-?[0-9]+(?:\.[0-9]+)?)\s*([a-zA-Z]+)?$/)
  if (!match) return null
  const [, low, high, unit = ''] = match
  const digits = Math.max(decimalPlaces(low), decimalPlaces(high))
  const lowNumber = Number(low)
  const highNumber = Number(high)
  const reference = key === 'height' || key === 'weight'
    ? `小不点 ≤${formatMetric(lowNumber + (highNumber - lowNumber) * .02, key)}${key === 'height' ? 'm' : 'kg'} · 大块头 ≥${formatMetric(highNumber - (highNumber - lowNumber) * .02, key)}${key === 'height' ? 'm' : 'kg'}`
    : key === 'voice' ? '粗嗓门 −100–−96 dB · 婉转声 96–100 dB' : ''
  return {
    key,
    label,
    low: formatValue(low),
    high: formatValue(high),
    unit,
    range: `${formatValue(low)}–${formatValue(high)}${unit ? ` ${unit}` : ''}`,
    span: (highNumber - lowNumber).toFixed(digits),
    reference,
  }
}

const entries = computed(() => {
  const fields: [RangeKey, string, string][] = [
    ['height', '身高', props.ranges.height],
    ['weight', '体重', props.ranges.weight],
  ]
  if (!props.egg) fields.push(['voice', '声音', '-100–100 dB'])
  return fields
    .map(([key, label, value]) => parseRange(key, label, value))
    .filter((entry): entry is RangeEntry => entry !== null)
})
const hasHabitat = computed(() => !props.egg && Boolean(props.areas?.length))
const hasContent = computed(() => entries.value.length > 0 || hasHabitat.value)
</script>
<template>
  <section v-if="hasContent" class="mini-panel mini-axes">
    <h4>{{ egg ? '精灵蛋' : '能力值' }} · 数据范围</h4>
    <div v-for="entry in entries" :key="entry.key" class="mini-axis" :class="entry.key">
      <div class="mini-axis-heading">
        <b>{{ entry.label }} {{ entry.range }}</b>
        <span>参考范围</span>
        <small>范围跨度 {{ entry.span }}{{ entry.unit ? ` ${entry.unit}` : '' }}</small>
      </div>
      <div class="mini-axis-scale">
        <span>{{ entry.low }}{{ entry.unit ? ` ${entry.unit}` : '' }}</span>
        <div class="mini-axis-track" role="img" :aria-label="`${entry.label}范围 ${entry.range}`"><i></i></div>
        <span>{{ entry.high }}{{ entry.unit ? ` ${entry.unit}` : '' }}</span>
      </div>
      <div class="mini-axis-caption"><small>最小值</small><small>最大值</small></div>
      <p v-if="entry.reference" class="mini-axis-reference"><span>{{ entry.key === 'voice' ? '声音参考' : '体型参考' }}</span><b>{{ entry.reference }}</b></p>
    </div>
    <div v-if="hasHabitat" class="mini-habitat"><span>栖息分布</span><b>{{ areas?.join('、') }}</b></div>
  </section>
</template>
