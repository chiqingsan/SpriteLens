<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import type { Pet } from '../types/pets'
import UiIcon from './UiIcon.vue'
import PetMarks from './PetMarks.vue'
const { pet } = defineProps<{ pet: Pet }>()
const image = ref(0)
const urls = computed(() => [pet.artwork_url])
const stage = ref<HTMLElement>()
const frame = ref({ width: 0, height: 0, pixelRatio: window.devicePixelRatio })
const bounds = ref<{ left: number; top: number; width: number; height: number; sourceWidth: number; sourceHeight: number }>()
const imageStyle = computed(() => {
  if (!bounds.value || !frame.value.width) return { visibility: 'hidden' as const }
  const box = bounds.value
  // 同源素材按角色边界缩放；原图像素不足时限制放大，避免头像变成模糊的“大立绘”。
  const scale = Math.min(Math.min(frame.value.width, 220) / box.width, frame.value.height / box.height, 1 / frame.value.pixelRatio)
  return { width: box.sourceWidth * scale + 'px', height: box.sourceHeight * scale + 'px',
    left: (frame.value.width - box.width * scale) / 2 - box.left * scale + 'px',
    top: (frame.value.height - box.height * scale) / 2 - box.top * scale + 'px' }
})
function failImage() { bounds.value = undefined; image.value++ }
function fitImage(event: Event) {
  const source = event.target as HTMLImageElement
  const canvas = document.createElement('canvas')
  canvas.width = source.naturalWidth; canvas.height = source.naturalHeight
  const context = canvas.getContext('2d', { willReadFrequently: true })!
  context.drawImage(source, 0, 0)
  const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data
  let left = canvas.width, top = canvas.height, right = -1, bottom = -1
  for (let y = 0; y < canvas.height; y++) for (let x = 0; x < canvas.width; x++) {
    if (pixels[(y * canvas.width + x) * 4 + 3]) {
      left = Math.min(left, x); top = Math.min(top, y); right = Math.max(right, x); bottom = Math.max(bottom, y)
    }
  }
  if (right < left) { failImage(); return }
  bounds.value = { left, top, width: right - left + 1, height: bottom - top + 1, sourceWidth: canvas.width, sourceHeight: canvas.height }
}
const observer = new ResizeObserver(([entry]) => {
  frame.value = { width: entry!.contentRect.width, height: entry!.contentRect.height, pixelRatio: window.devicePixelRatio }
})
onMounted(() => observer.observe(stage.value!))
onUnmounted(() => observer.disconnect())
// 特性表 id=1 的名称就是“无”，speciality_id=0 时返回“特性未知”，两者都视为无特性，只显示性格。
const hasSpeciality = computed(() => !/^(特性未知|无)$/.test(pet.detail.speciality_name))
const traits = computed(() => hasSpeciality.value ? pet.nature_name + ' · ' + pet.detail.speciality_name : pet.nature_name)
watch(() => pet.gid + ':' + urls.value.join('|'), () => { image.value = 0; bounds.value = undefined })
</script>
<template>
  <section class="pet-detail-art" :class="{ male: pet.gender === 1, female: pet.gender === 2 }" :aria-label="pet.name">
    <div ref="stage" class="detail-art-stage">
      <img v-if="image < 2 && urls[image]" :key="pet.gid + ':' + image" class="detail-artwork" :src="urls[image]" :alt="pet.species_name || pet.name" :style="imageStyle" @load="fitImage" @error="failImage">
      <span v-else class="detail-art-placeholder">{{ pet.name.slice(0, 1) }}</span>
    </div>
    <div class="detail-art-top">
      <div class="detail-art-heading"><div class="detail-art-name"><UiIcon v-if="pet.gender === 1 || pet.gender === 2" :name="pet.gender === 1 ? 'gender-male' : 'gender-female'" /><span v-else aria-label="性别未知">—</span><h2 :title="pet.name">{{ pet.name }}</h2></div><b class="detail-art-level">Lv.{{ pet.level }}</b></div>
      <div class="detail-art-meta"><div class="detail-art-identity"><small>No.{{ pet.dex_no || '—' }}</small><div v-if="pet.detail.types.length" class="detail-type-icons"><img v-for="type in pet.detail.types" :key="type.name" :src="type.icon_url" :alt="type.name" :title="type.name"></div></div><span class="detail-art-traits" :title="traits">{{ traits }}</span></div>
    </div>
    <div class="detail-art-groups"><span v-for="group in pet.egg_groups.filter(value => !/^(未知|未知组|未发现|未发现组|暂无数据)$/.test(value))" :key="group">{{ group }}</span></div>
    <div v-if="pet.is_shiny || pet.is_colorful" class="detail-art-rarity"><PetMarks :pet="pet" kind="card" /><PetMarks :pet="pet" kind="rarity" /></div>
  </section>
</template>
