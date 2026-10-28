<script setup lang="ts">
import { computed } from 'vue'
import type { EggBoxEntry } from '../types/eggBox'
import EggBoxArtwork from './EggBoxArtwork.vue'
import UiIcon from './UiIcon.vue'

const props = defineProps<{ egg: EggBoxEntry; selected: boolean; favoriteSaving: boolean }>()
const emit = defineEmits<{ select: [egg: EggBoxEntry, event: MouseEvent]; favorite: [egg: EggBoxEntry] }>()

const cardTags = computed(() => {
  const tags = props.egg.tags
  const voice = tags.voice || tags.medals.find(label => label === '婉转声' || label === '粗嗓门')
  return [
    ...(tags.nature ? [{ label: tags.nature, kind: 'nature' }] : []),
    ...(tags.weight ? [{ label: tags.weight, kind: 'weight' }] : []),
    ...(voice ? [{ label: voice, kind: 'voice' }] : []),
    ...tags.medals.filter(label => label !== voice).map(label => ({ label, kind: 'medal' })),
  ]
})
/* 标签行固定一行高：最多展示两枚，其余折叠成「+N」。
   有标签与没标签的卡片因此共用同一套行高，蛋图、名称、底栏在网格里全部对齐。 */
const MAX_TAGS = 2
const visibleTags = computed(() => cardTags.value.slice(0, MAX_TAGS))
const hiddenTagCount = computed(() => cardTags.value.length - visibleTags.value.length)
const tagsTitle = computed(() => cardTags.value.map(tag => tag.label).join('、'))

function height(value: number) { return value > 0 ? `${(value / 100).toFixed(2)}m` : '—' }
function weight(value: number) { return value > 0 ? `${(value / 1000).toFixed(3)}kg` : '—' }
function date(value: number) {
  return value > 0 ? new Date(value * 1000).toLocaleString('sv-SE', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }) : '获得时间未知'
}
</script>

<template>
  <article class="eggbox-card" :class="{ selected, favorite: egg.favorite }" :data-egg-instance="egg.instance_id">
    <button type="button" class="eggbox-card-select" :aria-pressed="selected" :aria-label="`${egg.egg_name}，编号${egg.instance_id}`" @click="emit('select', egg, $event)">
      <div class="eggbox-card-art" :title="egg.description || undefined">
        <div class="eggbox-card-topline">
          <span v-if="egg.tags.nest" class="eggbox-card-nest" :class="egg.tags.nest === '学院绿窝' ? 'green' : 'normal'" :title="egg.tags.nest">{{ egg.tags.nest }}</span>
          <span v-if="egg.hatching" class="eggbox-card-status" :title="`孵化中 ${Math.round(egg.hatch_progress * 100)}%`"><UiIcon name="clock" />{{ Math.round(egg.hatch_progress * 100) }}%</span>
        </div>
        <EggBoxArtwork :egg="egg" size="card" />
        <span v-if="egg.quantity > 1" class="eggbox-card-quantity" :title="`同种蛋 ${egg.quantity} 枚`">×{{ egg.quantity }}</span>
      </div>
      <strong class="eggbox-card-name" :title="egg.egg_name"><span v-if="egg.egg_activity" class="eggbox-card-activity" title="活动来源的蛋">活动</span><span class="eggbox-card-name-text">{{ egg.egg_name }}</span><img v-if="egg.egg_kind === 'shiny'" class="eggbox-card-shiny-icon" src="/static/rarity/shiny-fit.webp" alt="异色" title="异色蛋"></strong>
      <div class="eggbox-card-labels" :title="cardTags.length ? tagsTitle : undefined" aria-label="蛋标签">
        <span v-for="(tag, index) in visibleTags" :key="`${tag.kind}-${index}`" class="eggbox-card-tag" :class="`eggbox-card-tag--${tag.kind}`">{{ tag.label }}</span>
        <span v-if="hiddenTagCount > 0" class="eggbox-card-tag eggbox-card-tag--more">+{{ hiddenTagCount }}</span>
      </div>
      <div class="eggbox-card-foot">
        <div class="eggbox-card-measures">
          <span :title="`尺寸 ${height(egg.height_cm)}`"><UiIcon name="ruler-2" /><span class="sr-only">尺寸</span>{{ height(egg.height_cm) }}</span>
          <span :title="`重量 ${weight(egg.weight_g)}`"><UiIcon name="weight" /><span class="sr-only">重量</span>{{ weight(egg.weight_g) }}</span>
        </div>
        <time :datetime="egg.obtained_at > 0 ? new Date(egg.obtained_at * 1000).toISOString() : undefined"><UiIcon name="clock" />{{ date(egg.obtained_at) }}</time>
      </div>
    </button>
    <button type="button" class="eggbox-favorite-button" :class="{ active: egg.favorite }"
      :aria-label="egg.favorite ? '取消收藏' : '收藏这枚蛋'" :aria-pressed="egg.favorite" :disabled="favoriteSaving"
      @click="emit('favorite', egg)"><UiIcon :name="egg.favorite ? 'star-filled' : 'star'" /></button>
  </article>
</template>
