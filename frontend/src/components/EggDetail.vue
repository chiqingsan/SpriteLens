<script setup lang="ts">
import type { Egg } from '../types/eggDex'
import DexPortrait from './DexPortrait.vue'
import DexGender from './DexGender.vue'
import DexRanges from './DexRanges.vue'
import WikiAcquisition from './WikiAcquisition.vue'
const { egg } = defineProps<{ egg: Egg }>()
const emit = defineEmits<{ filterGroup: [group: string] }>()
function duration(seconds: number) {
  if (!seconds) return '暂无'
  if (seconds < 60) return `${Math.ceil(seconds)}秒`
  if (seconds < 3600) return `${Math.round(seconds / 60)}分钟`
  const hours = seconds / 3600
  return `${Number.isInteger(hours) ? hours : hours.toFixed(1)}小时`
}
</script>
<template>
  <div class="dex-mini">
    <h3 class="mini-detail-title">精灵蛋详情</h3>
    <section class="mini-hero egg"><div class="mini-visual"><DexPortrait :src="egg.egg_icon_url" :name="egg.egg_name" eager /><span>蛋#{{ egg.egg_conf_id }}</span></div><div class="mini-hero-info"><div class="mini-number">No.{{ egg.handbook_no || '—' }}</div><h3>{{ egg.egg_name }}</h3><p>孵化精灵：{{ egg.name }}</p><div class="mini-types"><span class="mini-stage">{{ egg.egg_type_name || '类型未知' }}</span></div><div class="mini-groups"><small>蛋组</small><button v-for="group in egg.egg_group_names" :key="group" @click="emit('filterGroup', group)">{{ group }}</button></div></div></section>
    <div class="mini-egg-summary"><section class="mini-panel mini-hatch-times"><h4>孵化时间</h4><div v-for="[label, speed] in [['原始', 1], ['5倍', 5], ['6倍', 6], ['30倍', 30]] as const" :key="label"><span>{{ label }}</span><b>{{ speed === 1 ? egg.hatch_label || duration(egg.hatch_seconds) : duration(egg.hatch_seconds / speed) }}</b></div></section><DexGender :male="egg.gender_male" :female="egg.gender_female" /></div>
    <DexRanges :ranges="egg.reference_ranges" egg />
    <section class="mini-panel mini-hatch-result"><h4>孵化形态</h4><button v-if="egg.base_id" data-goto-page="handbook" :data-catalog-id="egg.base_id"><DexPortrait :src="egg.icon_url" :name="egg.name" /><span><small>精灵蛋孵化后的对应形态</small><b>{{ egg.name }}</b><i>查看精灵图鉴 →</i></span></button><p v-else>暂无孵化形态数据</p></section>
    <details v-if="egg.wiki?.eggs.length" class="mini-panel mini-extra"><summary>特殊蛋说明与来源</summary><WikiAcquisition :wiki="egg.wiki" eggs-only /><p class="mini-note">按物种整理，不代表所选蛋的固定产出。</p></details>
    <p class="mini-note">倍率时间仅作换算参考，实际加速效果以游戏为准。</p>
    <footer v-if="egg.wiki" class="mini-source">B站Wiki · {{ egg.wiki.updated_at }} 收录 · <a :href="egg.wiki.source_url" target="_blank" rel="noopener noreferrer">查阅原始条目 ↗</a></footer>
  </div>
</template>
