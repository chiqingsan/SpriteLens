<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { BreederParent } from '../types/breederLibrary'
import MedalIcon from './MedalIcon.vue'
import UiIcon from './UiIcon.vue'
const props = defineProps<{ parent: BreederParent; selected?: boolean; compact?: boolean }>()
const emit = defineEmits<{ select: [parent: BreederParent]; open: [gid: string] }>()
const failed = ref(false)
// 体型越界不是错误，用琥珀色值标记；缺值统一 —，不参与比较。
const ratio = (value: number | null) => value === null
  ? { text: '—', out: false }
  : value < 0 || value > 1
    ? { text: '超界', out: true }
    : { text: `${Number((value * 100).toFixed(1))}%`, out: false }
const measures = computed(() => {
  const voice = props.parent.voice
  return [
    { label: '高', ...ratio(props.parent.height_ratio) },
    { label: '重', ...ratio(props.parent.weight_ratio) },
    { label: '声', text: voice === null ? '—' : `${voice} dB`, out: false },
  ]
})
const rarity = computed(() => props.parent.is_colorful
  ? props.parent.is_shiny ? 'shiny-colorful' : 'colorful'
  : props.parent.is_shiny ? 'shiny' : '')
const rarityLabel = computed(() => ({ shiny: '异色', colorful: '炫彩', 'shiny-colorful': '异色炫彩' } as Record<string, string>)[rarity.value] || '')
watch(() => props.parent.icon_url, () => { failed.value = false })
</script>
<template>
  <article class="breeder-card" :class="[{ selected, compact }, `gender-${parent.gender}`]">
    <button class="breeder-card-select" :aria-pressed="!!selected" :aria-label="`${selected ? '取消选择' : '选择'}${parent.gender === 1 ? '种公' : '种母'}${parent.name}，个体${parent.gid}`" @click="emit('select', parent)">
      <span class="breeder-identity">
        <span class="breeder-portrait"><img v-if="parent.icon_url && !failed" :src="parent.icon_url" alt="" loading="lazy" decoding="async" @error="failed = true"><span v-else>{{ parent.name.slice(0, 1) }}</span><UiIcon v-if="selected" name="circle-check" class="breeder-selected-mark" /></span>
        <span class="breeder-copy">
          <span class="breeder-card-title"><strong :title="parent.name">{{ parent.name }}</strong><small>#{{ parent.dex_no }}</small><span v-if="rarity" class="breeder-rarity" :title="rarityLabel"><img :src="`/static/rarity/${rarity}-fit.webp`" alt="" loading="lazy" decoding="async"></span><UiIcon class="breeder-gender" :name="parent.gender === 1 ? 'gender-male' : 'gender-female'" /></span>
          <span class="breeder-traits"><b class="chip">{{ parent.nature || '性格未知' }}</b><MedalIcon v-for="mark in parent.marks" :key="mark.name" :name="mark.name" :source="mark.source" /></span>
          <span class="breeder-groups" :title="parent.groups.join(' / ')">{{ parent.groups.join(' / ') }}</span>
        </span>
      </span>
      <span class="breeder-measures">
        <span v-for="measure in measures" :key="measure.label" class="breeder-measure" :class="{ 'is-out': measure.out }"><small>{{ measure.label }}</small><b>{{ measure.text }}</b></span>
      </span>
    </button>
    <footer><small>{{ parent.location ? `箱 ${parent.location.box_id} · ${parent.location.row} 行 ${parent.location.column} 列` : '位置未采集' }}</small><button class="breeder-detail-link" :aria-label="`在背包查看${parent.name}，个体${parent.gid}`" @click="emit('open', parent.gid)">详情<UiIcon name="chevron-right" /></button></footer>
  </article>
</template>
