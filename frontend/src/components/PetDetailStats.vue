<script setup lang="ts">
import { computed } from 'vue'
import type { Pet } from '../types/pets'
const { pet } = defineProps<{ pet: Pet }>()
const order = ['hp', 'spa', 'spd', 'spe', 'def', 'atk'] as const
// 对齐蛋神 detail-reference.js 的固定维度上限，字段顺序按本项目六维映射。
const maximums: Record<(typeof order)[number], number> = { hp: 290, spa: 192, spd: 183, spe: 145, def: 183, atk: 200 }
const rows = computed(() => order.map(key => pet.stats.find(stat => stat.key === key)))
function point(index: number, radius: number) { const angle = (index * 60 - 90) * Math.PI / 180; return `${110 + Math.cos(angle) * radius},${110 + Math.sin(angle) * radius}` }
function ring(radius: number) { return order.map((_, index) => point(index, radius)).join(' ') }
const shape = computed(() => rows.value.map((row, index) => {
  const ratio = Math.max(0, Math.min(1, (row?.race ?? 0) / maximums[order[index]!]))
  return point(index, 66 * ratio)
}).join(' '))
const labelLayout = [
  { x: 110, y: 11, anchor: 'middle', iconX: 21, valueY: 40 },
  { x: 214, y: 44, anchor: 'end', iconX: -54, valueY: 76 },
  { x: 214, y: 156, anchor: 'end', iconX: -54, valueY: 188 },
  { x: 110, y: 182, anchor: 'middle', iconX: 21, valueY: 212 },
  { x: 6, y: 156, anchor: 'start', iconX: 36, valueY: 188 },
  { x: 6, y: 44, anchor: 'start', iconX: 36, valueY: 76 },
] as const
</script>
<template>
  <section class="pet-detail-stats detail-block">
    <h3>当前六维属性</h3>
    <div class="detail-stats-visual">
      <svg v-if="pet.stats.length" class="detail-radar" viewBox="0 0 220 220" role="img" aria-label="六维种族值、天赋加成与性格方向">
        <polygon v-for="radius in [13.2, 26.4, 39.6, 52.8, 66]" :key="radius" :points="ring(radius)" class="radar-ring" />
        <line v-for="(_, index) in order" :key="index" x1="110" y1="110" :x2="point(index, 66).split(',')[0]" :y2="point(index, 66).split(',')[1]" class="radar-ring" />
        <polygon :points="shape" class="radar-value" />
        <template v-for="(row, index) in rows" :key="index">
          <g :transform="`translate(${labelLayout[index]!.x} ${labelLayout[index]!.y})`" class="radar-label-group">
            <svg v-if="row?.key === pet.nature_positive" :x="labelLayout[index]!.iconX" y="-8" width="16" height="16" viewBox="0 0 24 24" class="radar-nature-icon radar-nature-up" aria-hidden="true"><use href="/static/icons/sprite.svg#arrow-up" /></svg>
            <svg v-if="row?.key === pet.nature_negative" :x="labelLayout[index]!.iconX" y="-8" width="16" height="16" viewBox="0 0 24 24" class="radar-nature-icon radar-nature-down" aria-hidden="true"><use href="/static/icons/sprite.svg#arrow-down" /></svg>
            <text x="0" y="0" :text-anchor="labelLayout[index]!.anchor" dominant-baseline="central"><tspan class="radar-label">{{ row?.label }}</tspan></text>
          </g>
          <text :x="labelLayout[index]!.x" :y="labelLayout[index]!.valueY" :text-anchor="labelLayout[index]!.anchor">
            <tspan class="radar-number">{{ row?.race ?? '—' }}</tspan>
            <tspan v-if="row && row.talent_add !== 0" dx="4" class="radar-bonus" :class="{ highlighted: row.talent_add > 0 }">{{ row.talent_add > 0 ? '+' : '' }}{{ row.talent_add }}</tspan>
          </text>
        </template>
      </svg>
      <p v-else class="filter-note">暂无属性数据</p>
    </div>
  </section>
</template>
