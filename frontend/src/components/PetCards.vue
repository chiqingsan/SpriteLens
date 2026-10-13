<script setup lang="ts">
import type { Pet } from '../types/pets'
import { badgeStyle, gender, positionText } from './petDisplay'
defineProps<{ pets: Pet[]; selected: number | null; imageMode: string }>()
const emit = defineEmits<{ select: [gid: number, element: HTMLElement] }>()
function select(pet: Pet, event: Event) { emit('select', pet.gid, event.currentTarget as HTMLElement) }
import PetAvatar from './PetAvatar.vue'
import UiIcon from './UiIcon.vue'
import PetMarks from './PetMarks.vue'
</script>

<template>
  <article
    v-for="pet in pets" :key="pet.gid" class="pet-card" :class="[gender(pet), { selected: selected === pet.gid }]"
    :data-gid="pet.gid" role="button" tabindex="0" :aria-pressed="selected === pet.gid" :aria-label="'查看' + pet.name + '详情'"
    @click="select(pet, $event)" @keydown.enter.prevent="select(pet, $event)" @keydown.space.prevent="select(pet, $event)">
    <div class="pc-top">
      <span class="pc-gender" :class="gender(pet)" :aria-label="pet.gender === 1 ? '雄性' : pet.gender === 2 ? '雌性' : '性别未知'"><UiIcon v-if="pet.gender === 1 || pet.gender === 2" :name="pet.gender === 1 ? 'gender-male' : 'gender-female'"></UiIcon><span v-else>—</span></span>
      <span class="pc-nature">{{ pet.nature_name }}</span>
      <span class="pc-badges"><span v-for="(name, index) in pet.type_names" :key="name" class="type-badge" :style="badgeStyle(pet.type_colors[index] || '')">{{ name }}</span>
        <span v-if="!pet.type_names.length" class="type-badge" :style="badgeStyle('')">未知</span></span>
    </div>
    <div class="pc-body">
      <PetAvatar :pet="pet" klass="pc-avatar" :image-mode="imageMode"></PetAvatar>
      <div class="pc-lines"><span class="pc-name" :title="pet.name">{{ pet.name }}</span><span class="pc-sub">{{ pet.dex_no ? '#' + pet.dex_no : '编号 ' + pet.gid }}</span></div>
    </div>
    <div class="pc-stats">
      <div v-for="stat in pet.stats" :key="stat.key" class="pc-stat">
        <small>{{ stat.label }}</small><b>{{ stat.value }}</b>
        <span class="mini-bar"><i :style="{ width: stat.ratio * 100 + '%' }"></i><u v-if="stat.race_ratio" :style="{ left: stat.race_ratio * 100 + '%' }"></u></span>
      </div>
    </div>
    <div class="pc-foot">
      <PetMarks :pet="pet"></PetMarks>
      <span v-if="pet.egg_groups.length" class="pc-pct" data-pet-display="groups">{{ pet.egg_groups.join(' / ') }}</span>
      <span v-for="field in (['height', 'weight'] as const)" :key="field" class="pc-pct" :data-pet-display="field">{{ field === 'height' ? '身高 ' : '体重 ' }}{{ pet[field + '_text'] }}<small data-pet-display="positions" title="物种参考范围位置">{{ positionText(pet, field) }}</small></span>
      <span class="pc-pct" data-pet-display="voice">声音 {{ pet.voice_text }}{{ pet.voice_text === '暂无数据' ? '' : ' dB' }}</span>
      <span class="pc-talent" :style="badgeStyle(pet.talent_color)">{{ pet.talent_rank }}阶</span>
    </div>
  </article>
</template>
