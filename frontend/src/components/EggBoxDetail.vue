<script setup lang="ts">
import { computed, ref } from 'vue'
import type { EggBoxEntry, EggBoxRange } from '../types/eggBox'
import EggBoxArtwork from './EggBoxArtwork.vue'
import UiIcon from './UiIcon.vue'

const props = defineProps<{ egg: EggBoxEntry; position: number; total: number }>()
const emit = defineEmits<{ previous: []; next: []; close: [] }>()
const closeButton = ref<HTMLButtonElement>()

function rangePercent(value: number, range: EggBoxRange | null) {
  if (value <= 0 || !range) return null
  return (value - range.min) / (range.max - range.min) * 100
}
function bounded(value: number) { return Math.max(0, Math.min(100, value)) }
function height(value: number) { return value > 0 ? `${Number((value / 100).toFixed(2))} m` : '暂无数据' }
function weight(value: number) { return value > 0 ? `${Number((value / 1000).toFixed(3))} kg` : '暂无数据' }
function percent(position: number | null) {
  if (position === null) return '范围未知'
  if (position < 0 || position > 100) return '超界'
  return `${position.toFixed(2)}%`
}
function weightReference(value: number) { return String(Number(value.toFixed(2))) }
function date(value: number) { return value > 0 ? new Date(value * 1000).toLocaleString() : '未知' }
const measurements = computed(() => [
  { id: 'height', label: '尺寸', value: height(props.egg.height_cm),
    position: rangePercent(props.egg.height_cm, props.egg.measurement_ranges.height_cm),
    range: props.egg.measurement_ranges.height_cm, format: height },
  { id: 'weight', label: '重量', value: weight(props.egg.weight_g),
    position: rangePercent(props.egg.weight_g, props.egg.measurement_ranges.weight_g),
    range: props.egg.measurement_ranges.weight_g, format: weight },
])
const hatchStatus = computed(() => {
  if (props.egg.hatching) return '正在孵化'
  return props.egg.hatch_known ? '尚未开始孵化' : '当前孵化状态未知'
})

defineExpose({ focusClose: () => closeButton.value?.focus({ preventScroll: true }) })
</script>

<template>
  <header class="eggbox-detail-header">
    <div class="eggbox-detail-title"><h2>精灵蛋详情</h2><span>#{{ egg.instance_id }}</span></div>
    <div class="eggbox-detail-actions">
      <span class="sr-only">第 {{ position }} 枚，共 {{ total }} 枚</span>
      <button type="button" class="ghost-button small" aria-label="上一枚" :disabled="total < 2" @click="emit('previous')"><UiIcon name="chevron-left" /></button>
      <button type="button" class="ghost-button small" aria-label="下一枚" :disabled="total < 2" @click="emit('next')"><UiIcon name="chevron-right" /></button>
      <button ref="closeButton" type="button" class="ghost-button small eggbox-mobile-close" @click="emit('close')"><UiIcon name="x" />关闭</button>
    </div>
  </header>

  <section class="eggbox-detail-hero">
    <EggBoxArtwork :egg="egg" size="hero" />
    <div class="eggbox-detail-identity">
      <h3>{{ egg.egg_name }}</h3>
      <p>{{ egg.species_name || (egg.special_egg_conf_id ? '孵化前物种未确定' : '对应物种未知') }}</p>
      <div class="eggbox-detail-tags">
        <span v-for="group in egg.egg_group_names" :key="group" class="eggbox-tag">{{ group }}</span>
        <span v-if="!egg.egg_group_names.length" class="muted">{{ egg.special_egg_conf_id ? '蛋组孵化后确定' : '蛋组资料缺失' }}</span>
      </div>
    </div>
  </section>

  <aside v-if="egg.description" class="eggbox-detail-description">
    <p>{{ egg.description }}</p>
    <a v-if="egg.description_source" :href="egg.description_source" target="_blank" rel="noreferrer">来源：洛克王国世界 WIKI</a>
  </aside>

  <section class="eggbox-detail-section">
    <div class="eggbox-section-heading"><h3>数据对比</h3></div>
    <div class="eggbox-measurements">
      <article v-for="measurement in measurements" :key="measurement.id" class="eggbox-measurement" :class="`eggbox-measurement--${measurement.id}`">
        <div class="eggbox-measurement-heading">
          <span>{{ measurement.label }} <b>{{ measurement.value }}</b></span><strong>{{ percent(measurement.position) }}</strong>
        </div>
        <div class="eggbox-measurement-scale">
          <span>{{ measurement.range ? measurement.format(measurement.range.min) : '—' }}</span>
          <div class="eggbox-range-track" :class="{ 'is-unknown': measurement.position === null, 'is-outside': measurement.position !== null && (measurement.position < 0 || measurement.position > 100) }"
            role="img" :aria-label="`${measurement.label}${measurement.value}，范围位置${percent(measurement.position)}`"
          :title="measurement.range ? `${measurement.format(measurement.range.min)} — ${measurement.format(measurement.range.max)}` : '暂无目录范围'">
            <i v-if="measurement.position !== null" :style="{ width: `${bounded(measurement.position)}%` }"></i>
            <b v-if="measurement.position !== null" :style="{ left: `${bounded(measurement.position)}%` }"></b>
          </div>
          <span>{{ measurement.range ? measurement.format(measurement.range.max) : '—' }}</span>
        </div>
        <small v-if="measurement.id === 'weight' && measurement.range">
          体型参考：小不点 ≤{{ weightReference((measurement.range.min + (measurement.range.max - measurement.range.min) * .02) / 1000) }}kg · 大块头 ≥{{ weightReference((measurement.range.max - (measurement.range.max - measurement.range.min) * .02) / 1000) }}kg
        </small>
        <small v-else-if="!measurement.range" class="filter-note">暂无范围资料</small>
        <small v-if="measurement.position !== null && (measurement.position < 0 || measurement.position > 100)" class="eggbox-outside-note">实测值超出目录范围</small>
      </article>
    </div>
  </section>

  <section class="eggbox-detail-section eggbox-hatch-section">
    <div class="eggbox-section-heading"><h3>孵化信息</h3><span>{{ egg.hatch_label || '时长未知' }}</span></div>
    <div class="eggbox-hatch-content">
      <p class="eggbox-hatch-status" :class="{ active: egg.hatching }">{{ hatchStatus }}<template v-if="egg.hatching"> · {{ Math.round(egg.hatch_progress * 100) }}%</template></p>
      <div v-if="egg.hatching" class="eggbox-hatch-track"><i :style="{ width: `${Math.round(egg.hatch_progress * 100)}%` }"></i></div>
      <dl class="eggbox-detail-meta">
        <div><dt>获得时间</dt><dd>{{ date(egg.obtained_at) }}</dd></div>
        <div><dt>数量</dt><dd>{{ egg.quantity || 1 }} 枚</dd></div>
        <div><dt>记录来源</dt><dd>{{ egg.historical ? '历史缓存' : '已观察' }}</dd></div>
      </dl>
    </div>
  </section>
</template>
