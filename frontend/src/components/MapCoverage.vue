<script setup lang="ts">
import { computed, useId } from 'vue'
import { coveragePath } from '../domain/mapCoverage'
import type { NearbyCoverage } from '../types/nearby'
import type { WorldMapEntry } from '../types/worldMap'

const props = defineProps<{ coverage: NearbyCoverage | null; map: WorldMapEntry }>()
/** 同一条 d 供 mask / fill / border 三个节点复用：整张图只生成一次 path 字符串。 */
const d = computed(() => props.coverage ? coveragePath(props.coverage, props.map) : '')
const outsideMaskId = `coverage-outside-${useId()}`
</script>

<template>
  <g v-if="d" class="map-coverage" aria-hidden="true">
    <defs><mask :id="outsideMaskId" maskUnits="userSpaceOnUse" :width="map.image.width" :height="map.image.height" x="0" y="0"><rect :width="map.image.width" :height="map.image.height" fill="white" /><path :d="d" fill="black" /></mask></defs>
    <path class="map-coverage-fill" :d="d" />
    <path class="map-coverage-border" :d="d" :mask="`url(#${outsideMaskId})`" vector-effect="non-scaling-stroke" />
  </g>
</template>

<style scoped>
.map-coverage-fill { fill: var(--radar-attention-3); fill-opacity: .4; }
.map-coverage-border { fill: none; stroke: var(--panel); stroke-opacity: .95; stroke-width: 4; stroke-linejoin: round; }
</style>
