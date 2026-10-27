<script setup lang="ts">
import type { PetSlot, PetSummary } from '../types/pets'
import { gender, pointValue } from './petDisplay'
import PetAvatar from './PetAvatar.vue'
import UiIcon from './UiIcon.vue'
import PetMarks from './PetMarks.vue'
import PetPartnerMark from './PetPartnerMark.vue'

const props = defineProps<{ slot: PetSlot; index: number; pets: Map<number, PetSummary>; selected: number | null; teams: boolean; activeTeam: number }>()
const emit = defineEmits<{ select: [gid: number, element: HTMLElement] }>()
const labels = { empty: '空格', filtered: '筛掉', missing: '待补', unknown: '未采集', matched: '' }
const pet = () => props.slot.state === 'matched' ? props.pets.get(props.slot.gid!) : undefined
function select(event: Event) { const value = pet(); if (value) emit('select', value.gid, event.currentTarget as HTMLElement) }
function navigate(event: KeyboardEvent) {
  const step = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -6, ArrowDown: 6 }[event.key as 'ArrowLeft']
  if (!step) return
  event.preventDefault()
  const node = event.currentTarget as HTMLElement, grid = node.closest<HTMLElement>('#pet-grid')
  if (!grid) return
  const slot = Number(node.dataset.slot)
  for (let next = slot + step; next >= 1; next += step) {
    const target = grid.querySelector<HTMLElement>(`[data-slot="${next}"]`)
    if (target) { target.focus(); break }
    if (next > grid.querySelectorAll('[data-slot]').length) break
  }
}
</script>

<template>
  <button
    v-if="slot.state === 'matched' && pet()" type="button" class="point-pet" :class="[gender(pet()!), { selected: selected === pet()!.gid }]"
    :data-slot="index + 1" :data-gid="pet()!.gid" :aria-pressed="selected === pet()!.gid"
    :aria-label="pet()!.name + '，' + pet()!.nature_name + '，第 ' + (Math.floor(index / 6) + 1) + (teams ? ' 队第 ' : ' 行第 ') + (index % 6 + 1) + (teams ? ' 格' : ' 列')"
    @click="select($event)" @keydown="navigate">
    <span class="point-top"><span class="point-top-left"><span class="pc-gender" :class="gender(pet()!)" :aria-label="pet()!.gender === 1 ? '雄性' : pet()!.gender === 2 ? '雌性' : '性别未知'"><UiIcon v-if="pet()!.gender === 1 || pet()!.gender === 2" :name="pet()!.gender === 1 ? 'gender-male' : 'gender-female'"></UiIcon><span v-else>—</span></span><PetPartnerMark :pet="pet()!"></PetPartnerMark></span><span class="point-markers"><span class="point-rarity-slot"><PetMarks :pet="pet()!" kind="rarity"></PetMarks></span><span class="point-color-slot"><PetMarks :pet="pet()!" kind="card"></PetMarks></span></span><span class="point-nature" :title="pet()!.nature_name">{{ pet()!.nature_name }}</span></span>
    <span class="point-portrait-row"><span class="point-groups" data-pet-display="groups"><span v-for="groupIndex in [0, 1]" :key="groupIndex" class="point-group-slot"><span v-if="pet()!.egg_groups[groupIndex] && !/^(未知|未知组|未发现|未发现组|暂无数据)$/.test(pet()!.egg_groups[groupIndex]!)" class="point-egg-group" :title="pet()!.egg_groups[groupIndex]">{{ pet()!.egg_groups[groupIndex]!.replace(/组$/, '') }}</span></span></span><PetAvatar :pet="pet()!" klass="point-avatar"></PetAvatar><span class="point-medals"><PetMarks :pet="pet()!" kind="medals" slots></PetMarks></span></span>
    <span class="point-name" :title="pet()!.name">{{ pet()!.name }}</span><span class="point-metrics"><span v-for="field in (['height', 'weight', 'voice'] as const)" :key="field" :data-pet-display="field" :title="(field === 'height' ? '身高' : field === 'weight' ? '体重' : '声音') + ' · 实际值 ' + pet()![field + '_text']"><b>{{ pointValue(pet()!, field) }}</b><small v-if="field === 'voice' && pointValue(pet()!, field) !== '—'" class="metric-unit">db</small></span></span>
  </button>
  <div v-else class="pet-box-slot" :class="'slot-' + slot.state" :data-slot="index + 1" :aria-label="'第 ' + (Math.floor(index / 6) + 1) + (teams ? ' 队第 ' : ' 行第 ') + (index % 6 + 1) + (teams ? ' 格，' : ' 列，') + labels[slot.state]"><span>{{ labels[slot.state] }}</span></div>
</template>
