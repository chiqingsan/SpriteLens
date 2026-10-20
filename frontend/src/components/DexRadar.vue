<script setup lang="ts">
import { computed } from 'vue'
const { stats } = defineProps<{ stats: Record<string, number> }>()
const axes = [ ['hp', '生命', 290], ['spa', '魔攻', 192], ['spd', '魔防', 183], ['spe', '速度', 145], ['def', '物防', 183], ['atk', '物攻', 200] ] as const
function point(index: number, radius: number) {
  const angle = (-90 + index * 60) * Math.PI / 180
  return { x: 110 + Math.cos(angle) * radius, y: 110 + Math.sin(angle) * radius }
}
function polygon(radius: number) { return axes.map((_, index) => { const p = point(index, radius); return `${p.x},${p.y}` }).join(' ') }
const shape = computed(() => axes.map(([key, , max], index) => {
  const p = point(index, 68 * Math.max(0, Math.min(1, (stats[key] || 0) / max)))
  return `${p.x},${p.y}`
}).join(' '))
</script>
<template>
  <svg class="mini-radar" viewBox="0 0 220 220" role="img" aria-label="种族值雷达图">
    <polygon v-for="ratio in [.25, .5, .75, 1]" :key="ratio" :points="polygon(ratio * 68)" class="radar-grid" />
    <line v-for="(_, index) in axes" :key="index" x1="110" y1="110" :x2="point(index, 68).x" :y2="point(index, 68).y" class="radar-grid" />
    <polygon :points="shape" class="radar-shape" />
    <text v-for="([key, label], index) in axes" :key="key" :x="point(index, 91).x" :y="point(index, 91).y - 5" text-anchor="middle"><tspan :x="point(index, 91).x">{{ label }}</tspan><tspan :x="point(index, 91).x" dy="14">{{ stats[key] || '—' }}</tspan></text>
  </svg>
</template>
