<script setup lang="ts">
import { computed, reactive } from 'vue'
import type { Pet } from '../types/pets'
const { pet } = defineProps<{ pet: Pet }>()
const failed = reactive<Record<number, boolean>>({})
const medals = computed(() => pet.detail.awarded_medals ?? (pet.worn_medal_id ? [{ id: pet.worn_medal_id, name: pet.worn_medal_name + ' · 当前佩戴', icon_url: `/static/medal-icons/${pet.worn_medal_id}.png` }] : []))
</script>
<template>
  <section class="detail-medal-strip"><h3>全部奖牌</h3><div class="detail-medal-scroll" tabindex="0" aria-label="精灵奖牌，可横向滚动"><span v-for="medal in medals" :key="medal.id" class="detail-medal-icon" tabindex="0" role="img" :aria-label="medal.name" :title="medal.name"><img v-if="!failed[medal.id]" :src="medal.icon_url" alt="" @error="failed[medal.id] = true"><span v-else>{{ medal.name }}</span></span><small v-if="pet.detail.awarded_medals === null">集合未采集</small><small v-else-if="!medals.length">暂无奖牌</small></div></section>
</template>
