<script setup lang="ts">
import type { PetSlot, Pet } from '../types/pets'
import { gender, pointValue } from './petDisplay'
defineProps<{ slots: PetSlot[]; pets: Map<number, Pet>; selected: number | null; teams: boolean; activeTeam: number; imageMode: string }>()
const emit = defineEmits<{ select: [gid: number, element: HTMLElement] }>()
const labels = { empty: '空格', filtered: '筛掉', missing: '待补', unknown: '未采集', matched: '' }
function select(pet: Pet, event: Event) { emit('select', pet.gid, event.currentTarget as HTMLElement) }
function navigate(event: KeyboardEvent) {
  const step = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -6, ArrowDown: 6 }[event.key as 'ArrowLeft']
  if (!step) return
  event.preventDefault()
  const node = event.currentTarget as HTMLElement, original = Number(node.dataset.slot)
  for (let slot = original + step; slot >= 1; slot += step) {
    if (Math.abs(step) === 1 && Math.floor((slot - 1) / 6) !== Math.floor((original - 1) / 6)) break
    const grid = node.parentElement!, target = grid.querySelector<HTMLElement>(`button[data-slot="${slot}"]`)
    if (target) { target.focus(); break }
    if (slot > grid.querySelectorAll('[data-slot]').length) break
  }
}
import PetAvatar from './PetAvatar.vue'
import UiIcon from './UiIcon.vue'
import PetMarks from './PetMarks.vue'
</script>

<template>
  <template v-for="(slot, index) in slots" :key="(teams ? 'team-' : 'box-') + index">
    <div v-if="teams && index % 6 === 0" class="pet-team-heading">第 {{ Math.floor(index / 6) + 1 }} 队{{ activeTeam === Math.floor(index / 6) + 1 ? ' · 当前出战' : '' }}</div>
    <template v-for="pet in slot.state === 'matched' ? [pets.get(slot.gid!)!] : []" :key="pet.gid">
      <button
        type="button" class="point-pet" :class="[gender(pet), { selected: selected === pet.gid }]" :data-slot="index + 1" :data-gid="pet.gid"
        :aria-pressed="selected === pet.gid" :aria-label="pet.name + '，' + pet.nature_name + '，第 ' + (Math.floor(index / 6) + 1) + (teams ? ' 队第 ' : ' 行第 ') + (index % 6 + 1) + (teams ? ' 格' : ' 列')"
        @click="select(pet, $event)" @keydown="navigate">
        <span class="point-top"><span class="pc-gender" :class="gender(pet)" :aria-label="pet.gender === 1 ? '雄性' : pet.gender === 2 ? '雌性' : '性别未知'"><UiIcon v-if="pet.gender === 1 || pet.gender === 2" :name="pet.gender === 1 ? 'gender-male' : 'gender-female'"></UiIcon><span v-else>—</span></span><span class="point-markers"><span class="point-rarity-slot"><PetMarks :pet="pet" kind="rarity"></PetMarks></span><span class="point-color-slot"><PetMarks :pet="pet" kind="card"></PetMarks></span></span><span class="point-nature" :title="pet.nature_name">{{ pet.nature_name }}</span></span>
        <span class="point-portrait-row"><span class="point-groups" data-pet-display="groups"><span v-for="groupIndex in [0, 1]" :key="groupIndex" class="point-group-slot"><span v-if="pet.egg_groups[groupIndex] && !/^(未知|未知组|未发现|未发现组|暂无数据)$/.test(pet.egg_groups[groupIndex]!)" class="point-egg-group" :title="pet.egg_groups[groupIndex]">{{ pet.egg_groups[groupIndex]!.replace(/组$/, '') }}</span></span></span><PetAvatar :pet="pet" klass="point-avatar" :image-mode="imageMode"></PetAvatar><span class="point-medals"><PetMarks :pet="pet" kind="medals" slots></PetMarks></span></span>
        <span class="point-name" :title="pet.name">{{ pet.name }}</span><span class="point-metrics"><span v-for="field in (['height', 'weight', 'voice'] as const)" :key="field" :data-pet-display="field" :title="(field === 'height' ? '身高' : field === 'weight' ? '体重' : '声音') + ' · 实际值 ' + pet[field + '_text']"><b>{{ pointValue(pet, field) }}</b><small v-if="field === 'voice' && pointValue(pet, field) !== '—'" class="metric-unit">db</small></span></span>
      </button>
    </template>
    <div v-if="slot.state !== 'matched'" class="pet-box-slot" :class="'slot-' + slot.state" :data-slot="index + 1" :aria-label="'第 ' + (Math.floor(index / 6) + 1) + (teams ? ' 队第 ' : ' 行第 ') + (index % 6 + 1) + (teams ? ' 格，' : ' 列，') + labels[slot.state]"><span>{{ labels[slot.state] }}</span></div>
  </template>
</template>
