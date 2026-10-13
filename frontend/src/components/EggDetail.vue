<script setup lang="ts">
import type { Egg } from '../types/eggDex'
defineProps<{ egg: Egg }>()
function duration(seconds: number) {
  if (!seconds) return '—'
  if (seconds < 3600) return `${Math.round(seconds / 60)} 分钟`
  const hours = seconds / 3600
  return `${Number.isInteger(hours) ? hours : hours.toFixed(1)} 小时`
}
</script>
<template>
  <div class="detail-title"><h2>{{ egg.egg_name }}</h2><span class="muted">#{{ egg.egg_conf_id }}</span></div>
  <div class="detail-sub">{{ egg.name }}<template v-if="egg.handbook_no"> · 图鉴号 {{ egg.handbook_no }}</template> · {{ egg.egg_type_name || '普通' }}</div>
  <div class="detail-section">
    <h3>孵化时长</h3>
    <div v-for="[label, speed] in [['原始', 1], ['5 倍速', 5], ['6 倍速', 6], ['30 倍速', 30]] as const" :key="label" class="speed-row">
      <span>{{ label }}</span><b>{{ duration(egg.hatch_seconds / speed) }}</b>
    </div>
  </div>
  <div class="detail-section">
    <h3>公母比例</h3>
    <div v-if="egg.gender_male || egg.gender_female" class="gender-ring" :style="{ background: `conic-gradient(var(--male-strong) 0 ${egg.gender_male}%, var(--female-strong) ${egg.gender_male}% 100%)` }">
      <b>{{ egg.gender_male ? `♂ ${egg.gender_male}%` : `♀ ${egg.gender_female}%` }}</b>
    </div>
    <div v-else class="gender-ring unknown"><b>暂无数据</b></div>
  </div>
  <div class="detail-section"><h3>蛋基础范围</h3><div class="info-line">身高 {{ egg.reference_ranges.height }}</div><div class="info-line">体重 {{ egg.reference_ranges.weight }}</div></div>
  <div class="detail-section">
    <h3>进化链</h3><div class="skill-list">
    <template v-for="(base, index) in egg.chain" :key="base"><span v-if="index" class="chain-arrow">→</span><span class="skill-chip">{{ egg.chain_names[base] || (base === egg.base_id ? egg.name : `#${base}`) }}</span></template>
    <span v-if="!egg.chain.length" class="muted">—</span>
    </div>
  </div>
</template>
