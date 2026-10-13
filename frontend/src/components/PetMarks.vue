<script setup lang="ts">
import { computed, reactive } from 'vue'
import type { Pet, MedalMark } from '../types/pets'
const props = defineProps<{ pet: Pet; kind?: 'all' | 'rarity' | 'card' | 'medals'; slots?: boolean }>()
const failed = reactive<Record<string, boolean>>({})
const label = computed(() => (props.pet.is_shiny ? '异色' : '') + (props.pet.is_colorful ? '炫彩' : ''))
const rarity = computed(() => {
  let value = props.pet.is_colorful ? props.pet.is_shiny ? 'shiny-colorful' : 'colorful' : 'shiny'
  const id = props.pet.color_card?.card_id
  if (props.pet.is_colorful && /^(s[1-4]|1000)$/.test(String(id))) value = (id === '1000' ? 'blackwhite' : id) + '-' + value
  return value
})
const special = computed(() => /^(s[1-4]|1000)$/.test(props.pet.color_card?.card_id || ''))
const cardValid = computed(() => props.pet.color_card && (special.value || /^#[0-9a-f]{6}$/i.test(props.pet.color_card.base_color) && /^#[0-9a-f]{6}$/i.test(props.pet.color_card.mix_color)))
const pattern = computed(() => ({ 1: 'sparkle_four', 2: 'heart', 3: 'diamond', 4: 'star_outline' }[props.pet.color_card?.particle_id as 1]))
const marks = computed(() => props.slots ? ['大小', '粗婉'].map(group => props.pet.medal_marks.find(mark => group.includes(mark.label))) : props.pet.medal_marks)
function medalId(mark: MedalMark) { return { '大': 1001, '小': 1002, '粗': 1025, '婉': 1026 }[mark.label as '大'] }
function title(mark: MedalMark) { return mark.name + (mark.source === 'reference' ? ' · 体型/声音参考标记' : ' · 当前佩戴') }
</script>
<template>
  <span v-if="(!kind || kind === 'all' || kind === 'rarity') && (pet.is_shiny || pet.is_colorful)" class="pet-rarity" :title="label"><img v-if="!failed[rarity]" :src="'/static/rarity/' + rarity + '-fit.png'" :alt="label" @error="failed[rarity] = true"><template v-else>{{ label }}</template></span>
  <span v-if="(!kind || kind === 'all' || kind === 'card') && cardValid && pet.color_card" class="pet-color-card" role="img" :aria-label="pet.color_card.name + ' · ' + pet.color_card.particle_name" :title="pet.color_card.name + ' · ' + pet.color_card.particle_name">
    <img v-if="special && !failed['card-' + pet.color_card.card_id]" :src="'/static/color-cards/' + pet.color_card.card_id + '.png'" alt="" @error="failed['card-' + pet.color_card.card_id] = true">
    <template v-if="!special"><svg viewBox="0 0 100 60" preserveAspectRatio="none" aria-hidden="true"><rect width="100" height="60" :fill="pet.color_card.mix_color"></rect><path d="M0 30 Q25 12 50 30 T100 30 V60 H0 Z" :fill="pet.color_card.base_color"></path></svg><img v-if="pattern && !failed['pattern-' + pattern]" :src="'/static/color-cards/pattern_' + pattern + '.png'" alt="" @error="failed['pattern-' + pattern] = true"></template>
  </span>
  <template v-if="!kind || kind === 'all' || kind === 'medals'">
    <span v-for="(mark, index) in marks" :key="mark?.label || index" :class="{ 'point-medal-slot': slots }">
      <span v-if="mark" class="pet-medal" :class="{ 'has-icon': medalId(mark) && !failed[mark.label] }" :title="title(mark)"><span>{{ mark.label }}</span><img v-if="medalId(mark) && !failed[mark.label]" :src="'/static/medals/' + medalId(mark) + '.png'" :alt="mark.name" @error="failed[mark.label] = true"></span>
    </span>
  </template>
</template>
