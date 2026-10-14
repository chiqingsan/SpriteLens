<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import type { PetsModel } from '../composables/usePets'
import UiIcon from './UiIcon.vue'
const { model } = defineProps<{ model: PetsModel }>()
const { data, page, pages } = model
const emit = defineEmits<{ select: [value: number]; teams: [] }>()
const strip = ref<HTMLElement>()
function wheel(event: WheelEvent) {
  const node = strip.value!
  if (node.scrollWidth <= node.clientWidth) return
  event.preventDefault(); node.scrollLeft += event.deltaY || event.deltaX
}
function move(direction: number) { strip.value!.scrollLeft += direction * strip.value!.clientWidth * .75 }
watch(() => page.value, async () => {
  await nextTick()
  const node = strip.value?.querySelector<HTMLElement>('.active')
  if (!node || !strip.value) return
  if (node.offsetLeft < strip.value.scrollLeft) strip.value.scrollLeft = node.offsetLeft
  else if (node.offsetLeft + node.offsetWidth > strip.value.scrollLeft + strip.value.clientWidth) strip.value.scrollLeft = node.offsetLeft + node.offsetWidth - strip.value.clientWidth
})
</script>
<template>
  <div id="pet-page-navigation" class="pet-box-navigation" aria-label="自定义排序页码导航">
    <div class="box-navigation-row">
      <button class="ghost-button small box-teams" data-box="0" @click="emit('teams')">出战{{ data?.backpack.teams.length ? ' · ' + data.backpack.teams.reduce((sum, item) => sum + item.matched, 0) : '' }}</button>
      <button class="box-scroll" aria-label="向前滚动页码" :disabled="pages < 2" @click="move(-1)"><UiIcon name="chevron-left"></UiIcon></button>
      <div ref="strip" class="page-tab-strip" @wheel="wheel">
        <button v-for="number in pages" :key="number" class="box-number" :class="{ active: page === number }" :data-page="number" :aria-pressed="page === number" :title="'第 ' + number + ' 页'" @click="emit('select', number)">{{ number }}</button>
      </div>
      <button class="box-scroll" aria-label="向后滚动页码" :disabled="pages < 2" @click="move(1)"><UiIcon name="chevron-right"></UiIcon></button>
      <span class="box-total">第 {{ page }} / {{ pages }} 页 · 每页 30 只</span>
    </div>
  </div>
</template>
