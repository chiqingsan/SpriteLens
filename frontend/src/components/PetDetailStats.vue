<script setup lang="ts">
import { computed } from 'vue'
import type { Pet } from '../types/pets'
const { pet } = defineProps<{ pet: Pet }>()
const order = ['hp', 'spa', 'spd', 'spe', 'def', 'atk']
const rows = computed(() => order.map(key => pet.stats.find(stat => stat.key === key)))
const peak = computed(() => Math.max(1, ...pet.stats.map(stat => stat.value)))
const talent = computed(() => pet.stats.reduce((sum, stat) => sum + stat.talent_add, 0))
function point(index: number, radius: number) { const angle = (index * 60 - 90) * Math.PI / 180; return `${110 + Math.cos(angle) * radius},${110 + Math.sin(angle) * radius}` }
function ring(radius: number) { return order.map((_, index) => point(index, radius)).join(' ') }
const shape = computed(() => rows.value.map((row, index) => point(index, 66 * (row?.value || 0) / peak.value)).join(' '))
const labels = [[110, 18, 'middle'], [214, 54, 'end'], [214, 166, 'end'], [110, 190, 'middle'], [6, 166, 'start'], [6, 54, 'start']] as const
</script>
<template>
  <section class="pet-detail-stats detail-block">
    <h3>当前六维属性</h3><div class="detail-stat-total"><strong>{{ pet.stat_sum }}</strong><small>已含天赋加成 {{ talent >= 0 ? '+' : '' }}{{ talent }}</small></div>
    <svg v-if="pet.stats.length" class="detail-radar" viewBox="0 0 220 220" role="img" aria-label="当前六维属性相对分布"><polygon v-for="radius in [13.2, 26.4, 39.6, 52.8, 66]" :key="radius" :points="ring(radius)" class="radar-ring" /><line v-for="(_, index) in order" :key="index" x1="110" y1="110" :x2="point(index, 66).split(',')[0]" :y2="point(index, 66).split(',')[1]" class="radar-ring" /><polygon :points="shape" class="radar-value" /><text v-for="(row, index) in rows" :key="index" :x="labels[index]![0]" :y="labels[index]![1]" :text-anchor="labels[index]![2]"><tspan>{{ row?.label }}</tspan><tspan :x="labels[index]![0]" dy="22" class="radar-number">{{ row?.value ?? '—' }}</tspan></text></svg><p v-else class="filter-note">暂无属性数据</p>
    <details class="detail-stat-breakdown"><summary>展开六维明细</summary><table class="stat-table"><thead><tr><th>属性</th><th>当前</th><th>天赋</th><th>努力</th><th>种族</th></tr></thead><tbody><tr v-for="stat in pet.stats" :key="stat.key"><td>{{ stat.label }}</td><td>{{ stat.value }}</td><td>{{ stat.talent_add }}</td><td>{{ stat.effort_add }}</td><td>{{ stat.race }}</td></tr></tbody></table><small>当前值已含天赋与努力加成；雷达按本只精灵最大属性缩放。</small></details>
  </section>
</template>
