<script setup lang="ts">
import { computed } from 'vue'
import type { HandbookSpecies } from '../types/handbook'
import { typeBadgeStyle } from './handbookDisplay'

const { item } = defineProps<{ item: HandbookSpecies }>()
const order = ['hp', 'atk', 'spa', 'def', 'spd', 'spe'] as const
const labels: Record<(typeof order)[number], string> = {
  hp: '生命', atk: '物攻', spa: '魔攻', def: '物防', spd: '魔防', spe: '速度',
}
const peak = computed(() => Math.max(1, ...order.map(key => item.stats[key] || 0)))
const rows = computed(() => order.map(key => ({
  key, label: labels[key], value: item.stats[key] || 0,
  width: Math.round(((item.stats[key] || 0) / peak.value) * 100),
})))
const dexText = computed(() => item.handbook_no || (item.dex_no ? String(item.dex_no) : ''))
// 相性表里只有本物种自身系别有颜色资料，其余系别用中性底色。
const ownColors = computed(() => {
  const map: Record<string, string> = {}
  item.type_names.forEach((name, index) => { map[name] = item.type_colors[index] || '' })
  return map
})
function colorOf(name: string) { return ownColors.value[name] }
const hasMatchups = computed(() => Boolean(
  item.matchups.weak.length || item.matchups.resist.length || item.matchups.immune.length))
// 进化链优先展示完整链成员（含自身），没有链成员时退回 evolutions。
const chain = computed(() => (item.chain_members.length ? item.chain_members : item.evolutions))
</script>
<template>
  <div class="detail-title"><h2>{{ item.name }}</h2><span class="muted">#{{ item.key }}</span></div>
  <div class="detail-sub">
    <span class="muted">资料页（不读取账号数据）</span>
  </div>
  <div v-if="dexText || item.gender_ratio[0] || item.gender_ratio[1] || item.has_shiny" class="detail-sub">
    <template v-if="dexText">图鉴号 {{ dexText }}</template>
    <template v-if="item.gender_ratio[0] || item.gender_ratio[1]"> · 性别比 ♂{{ item.gender_ratio[0] }}% / ♀{{ item.gender_ratio[1] }}%</template>
    <template v-if="item.has_shiny"> · 有闪光形态</template>
  </div>

  <div v-if="item.description" class="detail-section"><h3>图鉴描述</h3><p class="species-desc">{{ item.description }}</p></div>

  <div class="detail-section"><h3>系别</h3>
    <div class="info-line">
      <span v-for="(name, index) in item.type_names" :key="name" class="type-badge" :style="typeBadgeStyle(item.type_colors[index])">{{ name }}</span>
      <span v-if="!item.type_names.length" class="muted">—</span>
    </div>
  </div>

  <div v-if="item.egg_groups.length" class="detail-section"><h3>蛋组</h3>
    <div class="skill-list"><span v-for="group in item.egg_groups" :key="group" class="skill-chip">{{ group }}</span></div>
  </div>

  <div v-if="hasMatchups" class="detail-section"><h3>属性相性</h3>
    <div class="info-line"><span class="muted">弱点</span>
      <span v-for="name in item.matchups.weak" :key="'w' + name" class="type-badge" :style="typeBadgeStyle(colorOf(name))">{{ name }}</span>
      <span v-if="!item.matchups.weak.length" class="muted">—</span>
    </div>
    <div class="info-line"><span class="muted">抵抗</span>
      <span v-for="name in item.matchups.resist" :key="'r' + name" class="type-badge" :style="typeBadgeStyle(colorOf(name))">{{ name }}</span>
      <span v-if="!item.matchups.resist.length" class="muted">—</span>
    </div>
    <div class="info-line"><span class="muted">免疫</span>
      <span v-for="name in item.matchups.immune" :key="'i' + name" class="type-badge" :style="typeBadgeStyle(colorOf(name))">{{ name }}</span>
      <span v-if="!item.matchups.immune.length" class="muted">—</span>
    </div>
  </div>

  <div v-if="item.egg" class="detail-section"><h3>精灵蛋</h3>
    <div class="info-line">{{ item.egg.name }} · 孵化 {{ item.egg.hatch_label }}<template v-if="item.egg.egg_type"> · {{ item.egg.egg_type }}蛋</template></div>
    <div v-if="item.egg.egg_groups.length" class="skill-list"><span v-for="group in item.egg.egg_groups" :key="group" class="skill-chip">{{ group }}</span></div>
    <div class="button-row"><button type="button" class="ghost-button small" data-goto-page="egg-dex">到蛋蛋图鉴看该蛋</button></div>
  </div>

  <div class="detail-section"><h3>物种参考范围</h3>
    <div class="info-line">身高 {{ item.reference_ranges.height || '暂无数据' }}</div>
    <div class="info-line">体重 {{ item.reference_ranges.weight || '暂无数据' }}</div>
  </div>

  <div class="detail-section"><h3>种族值</h3>
    <table class="stat-table"><tbody>
      <tr v-for="row in rows" :key="row.key">
        <td>{{ row.label }}</td><td class="num">{{ row.value }}</td>
        <td class="bar"><span class="detail-bar"><i :style="{ width: row.width + '%' }"></i></span></td>
      </tr>
    </tbody></table>
    <div class="info-line muted">总和 {{ item.stat_sum || 0 }}<template v-if="item.max_energy"> · 最大能量 {{ item.max_energy }}</template><template v-if="item.quality"> · 品质 {{ item.quality }}</template></div>
  </div>

  <div class="detail-section"><h3>进化链</h3>
    <div class="skill-list">
      <span v-for="evo in chain" :key="String(evo.key)" class="skill-chip">{{ evo.name }}（{{ evo.key }}）</span>
      <span v-if="!chain.length" class="muted">无进化记录</span>
    </div>
  </div>
</template>
