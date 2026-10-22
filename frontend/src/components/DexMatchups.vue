<script setup lang="ts">
import { computed } from 'vue'
import type { HandbookMatchups } from '../types/handbook'
import UiIcon from './UiIcon.vue'

const props = defineProps<{
  matchups: HandbookMatchups
  icons?: Record<string, string>
}>()

const groups = [
  { key: 'weak', label: '弱点', note: '受到更高伤害', icon: 'arrow-up', tone: 'weak' },
  { key: 'resist', label: '抵抗', note: '受到更低伤害', icon: 'circle-check', tone: 'resist' },
  { key: 'immune', label: '免疫', note: '不受该属性伤害', icon: 'filter-off', tone: 'immune' },
] as const
const visibleGroups = computed(() => groups.filter(group => props.matchups[group.key].length))
</script>

<template>
  <section v-if="visibleGroups.length" class="mini-panel dex-matchups" aria-labelledby="dex-matchups-title">
    <header class="dex-section-heading">
      <div>
        <h4 id="dex-matchups-title">属性相性</h4>
        <p>按防御属性整理的查询参考</p>
      </div>
      <UiIcon name="adjustments" aria-hidden="true" />
    </header>
    <div class="dex-matchup-groups">
      <article v-for="group in visibleGroups" :key="group.key" class="dex-matchup-group" :class="`is-${group.tone}`">
        <div class="dex-matchup-label">
          <UiIcon :name="group.icon" aria-hidden="true" />
          <span><b>{{ group.label }}</b><small>{{ group.note }}</small></span>
        </div>
        <div class="dex-matchup-types">
          <span v-for="name in props.matchups[group.key]" :key="name" class="dex-matchup-type">
            <img v-if="props.icons?.[name]" :src="props.icons[name]" :alt="`${name}系别`" loading="lazy" decoding="async">
            <span>{{ name }}</span>
          </span>
        </div>
      </article>
    </div>
  </section>
</template>
