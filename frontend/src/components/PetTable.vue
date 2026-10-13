<script setup lang="ts">
import type { Pet } from '../types/pets'
import { badgeStyle, positionText } from './petDisplay'
defineProps<{ pets: Pet[]; selected: number | null; imageMode: string }>()
const emit = defineEmits<{ select: [gid: number, element: HTMLElement] }>()
function select(pet: Pet, event: Event) { emit('select', pet.gid, event.currentTarget as HTMLElement) }
import PetAvatar from './PetAvatar.vue'
</script>

<template>
  <table id="pet-table" class="pet-table">
    <thead>
      <tr>
        <th class="col-pet">宠物</th><th class="col-types">系别</th><th class="col-nature">性格</th><th class="col-stats">六维</th>
        <th class="col-talent">天赋</th><th class="col-body">体型 / 声音</th><th class="col-skills">技能</th><th class="col-gid">编号</th>
      </tr>
    </thead><tbody id="pet-rows">
      <tr
        v-for="pet in pets" :key="pet.gid" :data-gid="pet.gid" :class="{ active: selected === pet.gid }" role="button" tabindex="0"
        :aria-pressed="selected === pet.gid" :aria-label="'查看' + pet.name + '详情'" @click="select(pet, $event)"
        @keydown.enter.prevent="select(pet, $event)" @keydown.space.prevent="select(pet, $event)">
        <td><div class="pet-cell"><PetAvatar :pet="pet" klass="pc-avatar" :image-mode="imageMode"></PetAvatar><div><strong>{{ pet.name }}</strong><small>{{ pet.species_name !== pet.name ? pet.species_name : '' }}</small></div></div></td>
        <td :class="{ 'col-types': !pet.type_names.length }"><span v-for="(name, index) in pet.type_names" :key="name" class="type-badge" :style="badgeStyle(pet.type_colors[index] || '')">{{ name }}</span><span v-if="!pet.type_names.length" class="muted">—</span></td>
        <td><div class="nature-cell"><strong>{{ pet.nature_name }}</strong><small><span v-if="pet.nature_positive" class="positive">↑{{ pet.nature_positive }}</span><span v-if="pet.nature_negative" class="negative">↓{{ pet.nature_negative }}</span></small></div></td>
        <td><div class="mini-stats"><div v-for="stat in pet.stats" :key="stat.key" class="mini-stat"><b>{{ stat.value }}</b><small>{{ stat.label }}</small><span class="mini-bar"><i :style="{ width: stat.ratio * 100 + '%' }"></i><u v-if="stat.race_ratio" :style="{ left: stat.race_ratio * 100 + '%' }"></u></span></div></div></td>
        <td><span class="talent-badge" :style="badgeStyle(pet.talent_color)">{{ pet.talent_rank }}阶</span></td>
        <td class="col-body">
          <div class="body-cell">
            <div v-for="field in (['height', 'weight'] as const)" :key="field" class="body-row" :title="positionText(pet, field)"><em>{{ field === 'height' ? '身高' : '体重' }}</em><span v-if="pet.range_positions[field].ratio !== null" class="body-bar" :aria-label="positionText(pet, field)"><i :class="field === 'height' ? 'h' : 'w'" :style="{ width: Number(pet[field + '_pct']) * 100 + '%' }"></i></span><span>{{ pet[field + '_text'] }}</span></div>
            <div class="body-row"><em>声音</em><span class="body-bar"><i class="v" :style="{ width: pet.voice_pct * 100 + '%' }"></i></span><span>{{ pet.voice_text }}{{ pet.voice_text === '暂无数据' ? '' : ' dB' }}</span></div>
          </div>
        </td>
        <td><div v-if="pet.skills.some(skill => skill.equipped)" class="skill-list"><span v-for="skill in pet.skills.filter(item => item.equipped)" :key="skill.name" class="skill-chip">{{ skill.name }}</span></div><span v-else class="muted">—</span></td>
        <td class="col-gid">{{ pet.gid }}</td>
      </tr>
    </tbody>
  </table>
</template>
