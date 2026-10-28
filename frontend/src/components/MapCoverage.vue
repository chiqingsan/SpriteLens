<script setup lang="ts">
import { computed, useId } from 'vue'
import { coveragePath } from '../domain/mapCoverage'
import type { NearbyCoverage } from '../types/nearby'
import type { WorldMapEntry } from '../types/worldMap'

const props = defineProps<{ coverage: NearbyCoverage | null; map: WorldMapEntry }>()
let previous: NearbyCoverage | null = null
let previousMap = '', previousPath = ''
/** 同版本快照仍要核对行内容：清除后版本号可能重新从 1 开始。 */
const d = computed(() => {
  const coverage = props.coverage
  if (!coverage) { previous = null; previousPath = ''; return '' }
  const { image, projection } = props.map
  const mapKey = `${image.width}:${image.height}:${projection.origin_x}:${projection.origin_y}:${projection.side}`
  if (previous && mapKey === previousMap && coverage.uid === previous.uid && coverage.map_id === previous.map_id
    && coverage.layer === previous.layer && coverage.scope === previous.scope && coverage.revision === previous.revision
    && coverage.cell_size === previous.cell_size && coverage.rows.length === previous.rows.length
    && coverage.rows.every((row, i) => row[0] === previous!.rows[i]![0] && row[1] === previous!.rows[i]![1] && row[2] === previous!.rows[i]![2])) return previousPath
  previous = coverage; previousMap = mapKey; previousPath = coveragePath(coverage, props.map)
  return previousPath
})
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
