<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { CollectionParent } from '../types/collectionLines'
import UiIcon from './UiIcon.vue'

const props = defineProps<{ parent: CollectionParent }>()
const emit = defineEmits<{ open: [gid: string] }>()
const failed = ref(false)
const markIds: Record<string, number> = { '大块头': 1001, '小不点': 1002, '婉转声': 1026, '粗嗓门': 1025 }
const marks = computed(() => props.parent.marks.map(mark => ({ ...mark, id: markIds[mark.name] })))
function percent(ratio: number | null) {
  return ratio === null ? '—' : ratio < 0 || ratio > 1 ? '超界' : `${Number((ratio * 100).toFixed(1))}%`
}
watch(() => props.parent.icon_url, () => { failed.value = false })
</script>

<template>
  <button class="collection-parent" :class="`gender-${parent.gender}`" :aria-label="`在背包查看${parent.gender === 2 ? '种母' : '种公'}${parent.name}`" :title="parent.basis.join(' / ')" @click="emit('open', parent.gid)">
    <span class="collection-parent-portrait"><img v-if="parent.icon_url && !failed" :src="parent.icon_url" alt="" loading="lazy" decoding="async" @error="failed = true"><span v-else>{{ parent.name.slice(0, 1) }}</span></span>
    <span class="collection-parent-copy"><span class="collection-parent-title"><strong>{{ parent.name }}</strong><UiIcon :name="parent.gender === 2 ? 'gender-female' : 'gender-male'" /><small>{{ parent.gender === 2 ? '种母' : '种公' }}</small></span><span class="collection-parent-traits"><b>{{ parent.nature }}</b><span class="collection-parent-marks"><img v-for="mark in marks" :key="mark.name" :src="`/static/medal-icons/${mark.id}.png`" :alt="mark.name" :title="`${mark.name}：${mark.source === 'worn' ? '当前佩戴' : '数值参考，非奖牌确认'}`"></span></span><span class="collection-parent-measures"><span>高 {{ percent(parent.height_ratio) }}</span><span>重 {{ percent(parent.weight_ratio) }}</span><span>{{ parent.voice }} dB</span></span><small class="collection-parent-location">{{ parent.location ? `箱 ${parent.location.box_id} · ${parent.location.row} 行 ${parent.location.column} 列` : '位置未采集' }} · {{ parent.marks.every(mark => mark.source === 'worn') ? '当前佩戴' : '含数值参考' }}</small></span>
    <UiIcon name="chevron-right" />
  </button>
</template>
