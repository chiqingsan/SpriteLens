<script setup lang="ts">
import { computed } from 'vue'
import type { PetSlot, PetSummary } from '../types/pets'
import PetSlotCell from './PetSlotCell.vue'

const props = defineProps<{ slots: PetSlot[]; pets: Map<number, PetSummary>; selected: number | null; teams: boolean; activeTeam: number }>()
const emit = defineEmits<{ select: [gid: number, element: HTMLElement] }>()

const groups = computed(() => {
  const out: { index: number; items: { slot: PetSlot; index: number }[] }[] = []
  props.slots.forEach((slot, index) => {
    const group = Math.floor(index / 6)
    if (!out[group]) out[group] = { index: group, items: [] }
    out[group]!.items.push({ slot, index })
  })
  return out
})
</script>

<template>
  <template v-if="!teams">
    <PetSlotCell v-for="(slot, index) in slots" :key="'box-' + index" :slot="slot" :index="index" :pets="pets" :selected="selected" :teams="false" :active-team="0" @select="(gid: number, element: HTMLElement) => emit('select', gid, element)"></PetSlotCell>
  </template>
  <template v-else>
    <section v-for="group in groups" :key="'team-' + group.index" class="pet-team-group" :class="{ 'is-active': activeTeam === group.index + 1 }" role="group" :aria-label="'第 ' + (group.index + 1) + ' 队'">
      <header class="pet-team-group-head">
        <span class="pet-team-name">第 {{ group.index + 1 }} 队</span>
        <span v-if="activeTeam === group.index + 1" class="pet-team-badge">当前出战</span>
      </header>
      <div class="pet-team-grid">
        <PetSlotCell v-for="item in group.items" :key="item.index" :slot="item.slot" :index="item.index" :pets="pets" :selected="selected" :teams="true" :active-team="activeTeam" @select="(gid: number, element: HTMLElement) => emit('select', gid, element)"></PetSlotCell>
      </div>
    </section>
  </template>
</template>
