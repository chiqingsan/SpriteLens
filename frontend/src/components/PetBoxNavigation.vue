<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import type { PetsModel } from '../composables/usePets'
import UiIcon from './UiIcon.vue'
const { model } = defineProps<{ model: PetsModel }>()
const { data, boxes, box, teams } = model
const emit = defineEmits<{ select: [id: number] }>()
const strip = ref<HTMLElement>()
function wheel(event: WheelEvent) {
  const node = strip.value!
  if (node.scrollWidth <= node.clientWidth) return
  event.preventDefault(); node.scrollLeft += event.deltaY || event.deltaX
}
function move(direction: number) { strip.value!.scrollLeft += direction * strip.value!.clientWidth * .75 }
watch(() => box.value?.box_id, async () => {
  await nextTick()
  const node = strip.value?.querySelector<HTMLElement>('.active')
  if (!node || !strip.value) return
  if (node.offsetLeft < strip.value.scrollLeft) strip.value.scrollLeft = node.offsetLeft
  else if (node.offsetLeft + node.offsetWidth > strip.value.scrollLeft + strip.value.clientWidth) strip.value.scrollLeft = node.offsetLeft + node.offsetWidth - strip.value.clientWidth
})
</script>
<template>
  <div id="pet-box-navigation" class="pet-box-navigation" aria-label="游戏箱号导航">
    <div class="box-navigation-row">
      <button class="ghost-button small box-teams" :class="{ active: teams }" data-box="0" :aria-pressed="teams" @click="emit('select', 0)">出战{{ data?.backpack.teams.length ? ' · ' + data.backpack.teams.reduce((sum, item) => sum + item.matched, 0) : '' }}</button>
      <button class="box-scroll" aria-label="向前滚动箱号" :disabled="!boxes.length" @click="move(-1)"><UiIcon name="chevron-left"></UiIcon></button>
      <div ref="strip" class="box-tab-strip" @wheel="wheel">
        <button v-for="item in boxes" :key="item.box_id" class="box-number" :class="{ active: !teams && item === box, 'box-hit': data?.backpack.filtering && item.matched }" :data-box="item.box_id" :aria-pressed="!teams && item === box" :title="'第 ' + item.box_id + ' 箱 · 命中 ' + item.matched + ' 只' + (item.historical ? ' · 历史箱表' : '') + (item.unknown ? ' · 有未采集槽位' : '')" @click="emit('select', item.box_id)">{{ item.box_id }}</button>
      </div>
      <button class="box-scroll" aria-label="向后滚动箱号" :disabled="!boxes.length" @click="move(1)"><UiIcon name="chevron-right"></UiIcon></button>
      <span class="box-total">共 {{ boxes.length }} 箱</span>
    </div>
  </div>
</template>
