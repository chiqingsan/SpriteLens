<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import UiIcon from './UiIcon.vue'

/* 统一分页条：页码横向滚动 + 左右翻页 + 总数说明。
   图鉴 / 蛋图鉴 / 双牌产线等页面共用同一套外观与键盘行为。 */
const props = withDefaults(defineProps<{
  page: number
  pages: number
  pageSize?: number
  label?: string
  unit?: string
}>(), { label: '分页', unit: '条' })
const emit = defineEmits<{ (event: 'update:page', value: number): void }>()

const strip = ref<HTMLElement>()
const reduced = window.matchMedia('(prefers-reduced-motion: reduce)')

function go(value: number) {
  const next = Math.max(1, Math.min(props.pages, value || 1))
  if (next !== props.page) emit('update:page', next)
}

function scrollStrip(direction: number) {
  const node = strip.value
  if (!node) return
  node.scrollBy({ left: direction * node.clientWidth * 0.75, behavior: reduced.matches ? 'auto' : 'smooth' })
}

function wheel(event: WheelEvent) {
  const node = strip.value
  if (!node || node.scrollWidth <= node.clientWidth) return
  event.preventDefault()
  node.scrollLeft += event.deltaY || event.deltaX
}

watch(() => props.page, async () => {
  await nextTick()
  const view = strip.value
  const node = view?.querySelector<HTMLElement>('.active')
  if (!view || !node) return
  if (node.offsetLeft < view.scrollLeft) view.scrollLeft = node.offsetLeft
  else if (node.offsetLeft + node.offsetWidth > view.scrollLeft + view.clientWidth) {
    view.scrollLeft = node.offsetLeft + node.offsetWidth - view.clientWidth
  }
})
</script>

<template>
  <nav class="ui-pager" :aria-label="label">
    <button class="ui-pager__scroll" type="button" aria-label="向前滚动页码" :disabled="pages < 2" @click="scrollStrip(-1)"><UiIcon name="chevron-left" /></button>
    <div ref="strip" class="ui-pager__strip" @wheel="wheel">
      <button v-for="number in pages" :key="number" type="button" class="ui-pager__num" :class="{ active: page === number }" :aria-pressed="page === number" :title="`第 ${number} 页`" @click="go(number)">{{ number }}</button>
    </div>
    <button class="ui-pager__scroll" type="button" aria-label="向后滚动页码" :disabled="pages < 2" @click="scrollStrip(1)"><UiIcon name="chevron-right" /></button>
    <span class="ui-pager__total">第 {{ page }} / {{ pages }} 页<span v-if="pageSize"> · 每页 {{ pageSize }} {{ unit }}</span></span>
  </nav>
</template>
