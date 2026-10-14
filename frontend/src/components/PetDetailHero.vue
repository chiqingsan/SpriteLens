<script setup lang="ts">
import { computed } from 'vue'
import type { Pet } from '../types/pets'
import UiIcon from './UiIcon.vue'
import PetMarks from './PetMarks.vue'
import PetArtwork from './PetArtwork.vue'
const { pet } = defineProps<{ pet: Pet }>()
// 特性表 id=1 的名称就是“无”，speciality_id=0 时返回“特性未知”，两者都视为无特性，只显示性格。
const hasSpeciality = computed(() => !/^(特性未知|无)$/.test(pet.detail.speciality_name))
const traits = computed(() => hasSpeciality.value ? pet.nature_name + ' · ' + pet.detail.speciality_name : pet.nature_name)
</script>
<template>
  <section class="pet-detail-art" :class="{ male: pet.gender === 1, female: pet.gender === 2 }" :aria-label="pet.name">
    <PetArtwork :src="pet.artwork_url" :alt="pet.species_name || pet.name" :placeholder="pet.name.slice(0, 1)" />
    <div class="detail-art-top">
      <div class="detail-art-heading"><div class="detail-art-name"><UiIcon v-if="pet.gender === 1 || pet.gender === 2" :name="pet.gender === 1 ? 'gender-male' : 'gender-female'" /><span v-else aria-label="性别未知">—</span><div class="detail-art-title"><h2 :title="pet.name">{{ pet.name }}</h2><small>No.{{ pet.dex_no || '—' }}</small></div></div><b class="detail-art-level">Lv.{{ pet.level }}</b></div>
      <div class="detail-art-meta"><div v-if="pet.detail.types.length" class="detail-type-icons"><img v-for="type in pet.detail.types" :key="type.name" :src="type.icon_url" :alt="type.name" :title="type.name"></div><span class="detail-art-traits" :title="traits">{{ traits }}</span></div>
    </div>
    <div class="detail-art-groups"><span v-for="group in pet.egg_groups.filter(value => !/^(未知|未知组|未发现|未发现组|暂无数据)$/.test(value))" :key="group">{{ group }}</span></div>
    <div v-if="pet.is_shiny || pet.is_colorful" class="detail-art-rarity"><PetMarks :pet="pet" kind="card" /><PetMarks :pet="pet" kind="rarity" /></div>
  </section>
</template>
