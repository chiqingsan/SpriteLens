<script setup lang="ts">
import { computed } from 'vue'
import type { HandbookSpecies } from '../types/handbook'
import { typeBadgeStyle } from './handbookDisplay'
import DexPortrait from './DexPortrait.vue'
import DexRadar from './DexRadar.vue'
import DexGender from './DexGender.vue'
import DexRanges from './DexRanges.vue'
import WikiSkills from './WikiSkills.vue'
import WikiAcquisition from './WikiAcquisition.vue'
const { item } = defineProps<{ item: HandbookSpecies }>()
const emit = defineEmits<{ navigate: [key: string | number]; filterGroup: [group: string] }>()
const dexText = computed(() => item.handbook_no || item.dex_no || '—')
const stage = computed(() => ({ 1: 'I阶', 2: 'II阶', 3: 'III阶', 4: '最终形态' })[item.stage] || '阶段未知')
const form = computed(() => item.name.match(/[（(](.*)[）)]/)?.[1] || stage.value)
const chain = computed(() => item.chain_members.length ? item.chain_members : item.evolutions)
</script>
<template>
  <div class="dex-mini">
    <h3 class="mini-detail-title">精灵详情</h3>
    <section class="mini-hero">
      <button v-if="item.egg" class="mini-breed-entry" data-goto-page="egg-dex" :data-catalog-id="item.egg.egg_conf_id" :title="`${item.egg.name} · ${item.egg.hatch_label}`"><DexPortrait :src="item.egg.icon_url || ''" :name="item.egg.name" /><small>查看精灵蛋</small></button>
      <div class="mini-visual"><DexPortrait :src="item.artwork_url || item.icon_url" :name="item.name" eager /><span>No.{{ dexText }}</span></div>
      <div class="mini-hero-info"><div class="mini-number">No.{{ dexText }}</div><h3>{{ item.name }}</h3>
        <div class="mini-types"><span v-for="(name, index) in item.type_names" :key="name" class="type-badge" :style="typeBadgeStyle(item.type_colors[index])">{{ name }}</span><span class="mini-stage">{{ stage }}</span></div>
        <div class="mini-groups"><small>蛋组</small><button v-for="group in item.egg_groups" :key="group" @click="emit('filterGroup', group)">{{ group }}</button><span v-if="!item.egg_groups.length">暂无蛋组</span></div>
        <div class="mini-meta"><div><span>形态</span><b>{{ form }}</b></div><div><span>异色</span><b>{{ item.has_shiny ? '有异色' : '无异色' }}</b></div></div>
      </div>
    </section>
    <section class="mini-panel mini-stats"><header><h4>种族值</h4><span>总和 <b>{{ item.stat_sum || '—' }}</b></span></header>
      <div class="mini-stats-layout"><div class="mini-radar-box"><DexRadar :stats="item.stats" /></div><div class="mini-stats-side"><section class="mini-feature"><h4>特性</h4><b>{{ item.wiki?.feature?.name || '暂无数据' }}</b><p>{{ item.wiki?.feature?.description || '该精灵暂未收录特性资料' }}</p></section><DexGender :male="item.gender_ratio[0]" :female="item.gender_ratio[1]" /></div></div>
    </section>
    <DexRanges :ranges="item.reference_ranges" :areas="item.wiki?.areas" />
    <section class="mini-panel mini-description"><h4>描述</h4><p>{{ item.description || '暂无精灵介绍' }}</p></section>
    <section class="mini-panel mini-family"><h4>进化链 <small>点击精灵查看图鉴</small></h4><div class="mini-family-members"><button v-for="(member, index) in chain" :key="member.key" :class="{ active: String(member.key) === item.key }" :aria-current="String(member.key) === item.key ? 'true' : undefined" @click="emit('navigate', member.key)"><small>{{ index + 1 }}</small><DexPortrait :src="member.icon_url || (String(member.key) === item.key ? item.icon_url : '')" :name="member.name" /><i>{{ member.stage ? member.stage === 1 ? '初始' : `第${member.stage}阶` : '关联形态' }}</i><span>{{ member.name }}</span></button><p v-if="!chain.length" class="muted">暂无进化记录</p></div><p class="mini-note">关联形态含分支，不表示依次进化。</p></section>
    <details v-if="item.wiki?.skills.length" class="mini-panel mini-extra"><summary>技能资料 · {{ item.wiki.skills.length }} 条学习记录</summary><WikiSkills :skills="item.wiki.skills" /></details>
    <details class="mini-panel mini-extra"><summary>属性相性</summary><div v-for="[label, names] in [['弱点', item.matchups.weak], ['抵抗', item.matchups.resist], ['免疫', item.matchups.immune]] as const" :key="label" class="mini-matchup"><b>{{ label }}</b><span v-for="name in names" :key="name" class="skill-chip">{{ name }}</span><span v-if="!names.length" class="muted">暂无记录</span></div></details>
    <details v-if="item.wiki?.evolutions.length" class="mini-panel mini-extra"><summary>进化条件</summary><div v-for="branch in item.wiki.evolutions" :key="branch.name" class="wiki-source-card"><strong>{{ branch.name }}</strong><p v-for="member in branch.members" :key="member.name">{{ member.name }} · {{ [member.level ? `Lv.${member.level}` : '', member.condition, member.item].filter(Boolean).join(' / ') || '初始形态或条件未收录' }}</p></div></details>
    <details v-if="item.wiki" class="mini-panel mini-extra"><summary>活动与特殊蛋来源</summary><WikiAcquisition :wiki="item.wiki" /></details>
    <footer class="mini-source"><span v-if="item.wiki">B站Wiki · {{ item.wiki.updated_at }} 收录 · </span><a :href="item.wiki?.source_url || `https://wiki.biligame.com/nrc/${encodeURIComponent(item.name)}`" target="_blank" rel="noopener noreferrer">查阅原始条目 ↗</a></footer>
  </div>
</template>
