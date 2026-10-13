<script setup lang="ts">
import { computed } from 'vue'
import type { Pet, PetBox } from '../types/pets'
import { badgeStyle } from './petDisplay'
import PetAvatar from './PetAvatar.vue'
import PetMarks from './PetMarks.vue'
const props = defineProps<{ pet: Pet; boxes: PetBox[]; imageMode: string }>()
const emit = defineEmits<{ locate: [id: number] }>()
const cn: Record<string, string> = { hp: '生命', atk: '物攻', spa: '魔攻', def: '物防', spd: '魔防', spe: '速度' }
const peak = computed(() => Math.max(0, ...props.pet.stats.map(stat => stat.value)))
const place = computed(() => props.pet.location)
const historical = computed(() => { const location = place.value; return location && ('team_id' in location ? location.historical : props.boxes.find(box => box.box_id === location.box_id)?.historical) })
</script>
<template>
  <div class="detail-hero"><PetAvatar :pet="pet" klass="pc-avatar" :image-mode="imageMode"></PetAvatar><div><div class="detail-title"><h2>{{ pet.name }}</h2><span class="muted">Lv{{ pet.level }}</span></div><div class="detail-sub">编号 {{ pet.gid }} · 图鉴 {{ pet.base_conf_id || '—' }}</div></div></div>
  <div class="point-tags"><PetMarks :pet="pet"></PetMarks></div>
  <p v-if="pet.worn_medal_id" class="info-line muted">佩戴奖牌：{{ pet.worn_medal_name }}</p>
  <div class="detail-section">
<h3>{{ place && 'team_id' in place ? '出战背包位置' : '游戏背包位置' }}</h3>
    <p v-if="!place" class="filter-note">暂无箱位或队伍位置，登录游戏后自动同步。</p>
    <template v-else>
<p class="info-line">{{ 'team_id' in place ? '第 ' + place.team_id + ' 队 · 第 ' + place.slot + ' 格' : '第 ' + place.box_id + ' 箱 · 第 ' + place.row + ' 行第 ' + place.column + ' 列' }}</p>
      <div v-if="'box_id' in place" class="pet-location-grid" role="img" aria-label="游戏背包位置"><span v-for="slot in 30" :key="slot" :class="{ active: slot === place.slot }"></span></div>
      <p class="filter-note">{{ historical ? '历史位置，登录后更新。' : '最近采集的位置，游戏内移动后自动更新。' }}</p>
      <button class="ghost-button small" :data-locate-team="'team_id' in place ? place.team_id : undefined" :data-locate-box="'box_id' in place ? place.box_id : undefined" @click="emit('locate', 'team_id' in place! ? 0 : place!.box_id)">{{ 'team_id' in place ? '定位到出战背包' : '定位到此箱' }}</button>
    </template>
  </div>
  <div class="detail-section"><h3>系别 / 性格</h3><div class="info-line"><span v-for="(name, index) in pet.type_names" :key="name" class="type-badge" :style="badgeStyle(pet.type_colors[index] || '')">{{ name }}</span><span v-if="!pet.type_names.length" class="muted">—</span></div><div class="info-line"><b>{{ pet.nature_name }} <span v-if="pet.nature_positive" class="positive">↑{{ cn[pet.nature_positive] || pet.nature_positive }}</span> <span v-if="pet.nature_negative" class="negative">↓{{ cn[pet.nature_negative] || pet.nature_negative }}</span></b></div></div>
  <div class="info-line muted">蛋组：{{ pet.egg_groups.join(' / ') || '暂无数据' }}</div>
  <div class="detail-section"><h3>六维对照</h3><table class="stat-table"><tbody><tr v-for="stat in pet.stats" :key="stat.key"><td>{{ stat.label }}</td><td class="num">{{ stat.value }}</td><td class="race">{{ stat.race || '—' }}</td><td class="bar"><span class="detail-bar"><i :style="{ width: (peak ? Math.min(1, stat.value / peak) : 0) * 100 + '%' }"></i><u :style="{ left: (peak ? Math.min(1, stat.race / peak) : 0) * 100 + '%' }"></u></span></td></tr></tbody></table><div class="info-line muted">数值 / 种族值（竖线为种族值参考）· 总和 {{ pet.stat_sum }}{{ pet.species_stat_sum ? ' / 种族 ' + pet.species_stat_sum : '' }}</div></div>
  <div class="detail-section"><h3>个体实际值 · 体型 / 声音</h3><div class="meta-grid"><div v-for="[label, value] in [['身高', pet.height_text], ['体重', pet.weight_text], ['声音', pet.voice_text + (pet.voice_text === '暂无数据' ? '' : ' dB')], ['天赋阶', pet.talent_rank + ' 阶']]" :key="label" class="meta-cell"><span>{{ label }}</span><b>{{ value }}</b></div></div></div>
  <div v-for="[title, ranges, positions] in [['物种参考范围', pet.reference_ranges, pet.range_positions], ['蛋基础范围', pet.egg_ranges, null]] as const" :key="title" class="detail-section"><h3>{{ title }}</h3><div v-for="field in ['height', 'weight'] as const" :key="field" class="info-line">{{ field === 'height' ? '身高 ' : '体重 ' }}{{ ranges[field] }}<template v-if="positions && positions[field].ratio !== null"> · {{ positions[field].status === 'within' ? '范围位置 ' + Math.round(positions[field].ratio! * 100) + '%' : '超出参考范围' }}<div class="reference-track" role="img" aria-label="物种参考范围位置"><i :style="{ left: Math.max(0, Math.min(1, positions[field].ratio!)) * 100 + '%' }"></i></div></template></div></div>
  <div class="detail-section"><h3>技能</h3><div class="skill-list"><span v-for="(skill, index) in pet.skills" :key="index" class="skill-chip">{{ skill.name }}{{ skill.equipped ? '' : '·未装备' }}</span><span v-if="!pet.skills.length" class="muted">无技能数据</span></div></div>
</template>
