<script setup lang="ts">
import { ref, watch } from 'vue'
import type { BreederParent } from '../types/breederLibrary'
import MedalIcon from './MedalIcon.vue'
import UiIcon from './UiIcon.vue'
const props = defineProps<{ parent: BreederParent; selected?: boolean; compact?: boolean }>()
const emit = defineEmits<{ select: [parent: BreederParent]; open: [gid: string] }>()
const failed = ref(false)
const percent = (value: number | null) => value === null ? '—' : value < 0 || value > 1 ? '超界' : `${Number((value * 100).toFixed(1))}%`
watch(() => props.parent.icon_url, () => { failed.value = false })
</script>
<template>
  <article class="breeder-card" :class="[{ selected, compact }, `gender-${parent.gender}`]">
    <button class="breeder-card-select" :aria-pressed="!!selected" :aria-label="`${selected ? '取消选择' : '选择'}${parent.gender === 1 ? '种公' : '种母'}${parent.name}，个体${parent.gid}`" @click="emit('select', parent)">
      <span class="breeder-portrait"><img v-if="parent.icon_url && !failed" :src="parent.icon_url" alt="" loading="lazy" decoding="async" @error="failed = true"><span v-else>{{ parent.name.slice(0, 1) }}</span></span>
      <span class="breeder-copy">
        <span class="breeder-card-title"><strong :title="parent.name">{{ parent.name }}</strong><small>#{{ parent.dex_no }}</small><UiIcon :name="parent.gender === 1 ? 'gender-male' : 'gender-female'" /></span>
        <span v-if="parent.is_shiny || parent.is_colorful" class="breeder-rarity">{{ parent.is_shiny ? '异色' : '' }}{{ parent.is_colorful ? '炫彩' : '' }}</span>
        <span class="breeder-traits"><b class="chip">{{ parent.nature || '性格未知' }}</b><MedalIcon v-for="mark in parent.marks" :key="mark.name" :name="mark.name" :source="mark.source" /></span>
        <span class="breeder-groups">{{ parent.groups.join(' / ') }}</span>
        <span class="breeder-measures"><span>高 {{ percent(parent.height_ratio) }}</span><span>重 {{ percent(parent.weight_ratio) }}</span><span>{{ parent.voice === null ? '声音 —' : `${parent.voice} dB` }}</span></span>
      </span>
      <UiIcon v-if="selected" name="circle-check" class="breeder-selected-mark" />
    </button>
    <footer><small>{{ parent.location ? `箱 ${parent.location.box_id} · ${parent.location.row} 行 ${parent.location.column} 列` : '位置未采集' }}</small><button class="breeder-detail-link" :aria-label="`在背包查看${parent.name}，个体${parent.gid}`" @click="emit('open', parent.gid)">详情<UiIcon name="chevron-right" /></button></footer>
  </article>
</template>
