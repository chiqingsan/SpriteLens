<script setup lang="ts">
import { computed, reactive } from 'vue'
import type { Pet, EvolutionNode } from '../types/pets'
const { pet } = defineProps<{ pet: Pet }>()
const failed = reactive<Record<number, boolean>>({})
const paths = computed(() => {
  const { nodes, edges } = pet.detail.evolution
  const byId = new Map(nodes.map(node => [node.id, node]))
  const result: EvolutionNode[][] = []
  function visit(node: EvolutionNode, path: EvolutionNode[]) {
    const next = edges.filter(edge => edge[0] === node.id && !path.some(item => item.id === edge[1])).map(edge => byId.get(edge[1])!)
    const current = [...path, node]
    if (next.length) next.forEach(target => visit(target, current))
    else result.push(current)
  }
  nodes.filter(node => !edges.some(edge => edge[1] === node.id)).forEach(node => visit(node, []))
  return result
})
</script>
<template>
  <section class="detail-evolution"><h3>进化关系</h3><p v-if="!paths.length" class="filter-note">暂无进化资料</p><div v-for="(path, index) in paths" :key="index" class="detail-evolution-path"><template v-for="(node, step) in path" :key="node.id"><span v-if="step" class="evolution-arrow" aria-label="进化为">→</span><figure :class="{ current: node.id === pet.base_conf_id }"><span class="evolution-avatar"><img v-if="node.portrait_url && !failed[node.id]" :src="node.portrait_url" alt="" @error="failed[node.id] = true"><span v-else>{{ node.name.slice(0, 1) }}</span></span><figcaption>No.{{ node.dex_no || '—' }} {{ node.name }}<small v-if="node.id === pet.base_conf_id">当前</small></figcaption></figure></template></div></section>
</template>
