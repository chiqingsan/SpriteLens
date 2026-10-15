<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import type { ApiClient } from '../api/client'
import { useEggDex } from '../composables/useEggDex'
import type { Egg } from '../types/eggDex'
import EggAvatar from '../components/EggAvatar.vue'
import EggDetail from '../components/EggDetail.vue'
import UiIcon from '../components/UiIcon.vue'
const props = defineProps<{ api: ApiClient; active: boolean }>()
const { filters, data, loading, error, load, pause, resume, clear } = useEggDex(props.api)
const visibleCount = ref(40)
const shownEggs = computed(() => data.value?.eggs.slice(0, visibleCount.value) || [])
const viewport = ref<HTMLElement>(), more = ref<HTMLElement>()
let observer: IntersectionObserver
const selected = ref<number | null>(null)
const egg = computed(() => data.value?.eggs.find(item => item.egg_conf_id === selected.value))
const content = ref<HTMLElement>()
const closeButton = ref<HTMLButtonElement>()
const narrow = window.matchMedia('(max-width: 1360px)')
const modal = ref(narrow.matches)
let trigger: HTMLElement | undefined
let inertNodes: HTMLElement[] = []
function syncInert() {
  inertNodes.forEach(node => { node.inert = false })
  inertNodes = []
  if (egg.value && modal.value) {
    inertNodes = [...document.querySelectorAll<HTMLElement>('.sidebar, .topbar'), content.value!]
    inertNodes.forEach(node => { node.inert = true })
  }
}
function resize() { modal.value = narrow.matches; syncInert() }
async function open(item: Egg, event: Event) {
  selected.value = item.egg_conf_id
  trigger = event.currentTarget instanceof HTMLElement ? event.currentTarget : undefined
  await nextTick()
  syncInert()
  closeButton.value?.focus({ preventScroll: true })
}
function close(restore = true) {
  selected.value = null
  syncInert()
  if (restore) trigger?.focus({ preventScroll: true })
}
function keydown(event: KeyboardEvent) {
  if (!egg.value) return
  if (event.key === 'Escape') { event.preventDefault(); close() }
  if (modal.value && event.key === 'Tab') {
    event.preventDefault()
    closeButton.value?.focus()
  }
}
watch(data, () => {
  visibleCount.value = 40
  if (viewport.value) viewport.value.scrollTop = 0
  if (selected.value !== null && !egg.value) close()
})
watch(() => props.active, value => { if (value) void resume(); else { close(false); pause() } }, { flush: 'sync' })
onMounted(() => {
  if (props.active) void resume(); else pause()
  observer = new IntersectionObserver(entries => {
    if (props.active && entries.some(entry => entry.isIntersecting)) visibleCount.value += 40
  }, { root: viewport.value, rootMargin: '200px' })
  observer.observe(more.value!)
  narrow.addEventListener('change', resize); document.addEventListener('keydown', keydown)
})
onUnmounted(() => { observer.disconnect(); close(false); narrow.removeEventListener('change', resize); document.removeEventListener('keydown', keydown) })
</script>
<template>
  <div class="workspace split" :class="{ 'detail-collapsed': !egg }" data-vue-page>
    <section ref="content" class="content-panel" :aria-busy="loading">
      <div class="panel-toolbar">
        <span id="ed-count" class="count-badge">收录 {{ data?.shown || 0 }} / {{ data?.total || 0 }} 种蛋</span>
        <label class="inline-field">搜索<input id="ed-search" v-model="filters.search" type="text" placeholder="名字 / 蛋编号"></label>
        <label class="inline-field">蛋组<select id="ed-group" v-model="filters.group"><option value="">全部蛋组</option><option v-for="group in data?.groups" :key="group">{{ group }}</option></select></label>
        <label class="inline-field">类型<select id="ed-type" v-model="filters.egg_type"><option value="">全部类型</option><option v-for="type in data?.egg_types" :key="type">{{ type }}</option></select></label>
        <label class="inline-field">孵化时长<select id="ed-hatch" v-model="filters.hatch_min_hours"><option value="">全部</option><option v-for="hours in [8, 12, 16, 20]" :key="hours" :value="String(hours)">≥ {{ hours }} 小时</option></select></label>
        <button type="button" class="ghost-button small" @click="clear">清除筛选</button>
      </div>
      <div ref="viewport" class="table-wrap">
        <div v-if="loading && !data" class="empty-hint" role="status"><UiIcon name="clock" />正在加载蛋图鉴…</div>
        <div v-else-if="error" class="empty-hint" role="alert"><UiIcon name="search" />蛋图鉴加载失败：{{ error }}<div class="button-row"><button class="ghost-button" @click="load">重试</button></div></div>
        <template v-else>
          <div id="ed-grid" class="hb-grid eggdex-grid">
            <article v-for="item in shownEggs" :key="item.egg_conf_id" class="hb-card" :class="{ active: selected === item.egg_conf_id }" role="button" tabindex="0" :aria-label="`查看${item.egg_name}详情`" :aria-pressed="selected === item.egg_conf_id" @click="open(item, $event)" @keydown.enter.prevent.stop="open(item, $event)" @keydown.space.prevent.stop="open(item, $event)">
              <div class="hb-head"><span class="hb-key">{{ item.handbook_no || '—' }}</span><EggAvatar :egg="item" /><div><strong>{{ item.egg_name }}</strong><small>{{ item.name }}</small></div></div>
              <div class="hb-meta"><span v-for="group in item.egg_group_names" :key="group" class="skill-chip">{{ group }}</span><span v-if="!item.egg_group_names.length" class="muted">—</span></div>
              <span class="hb-badge"><UiIcon name="clock" /> {{ item.hatch_label || '—' }}</span>
            </article>
          </div>
          <div v-if="data && !data.eggs.length" class="empty-hint"><UiIcon name="search" />{{ data.total ? '没有符合筛选条件的蛋' : '尚无蛋图鉴数据' }}<div v-if="data.total" class="button-row"><button class="ghost-button" @click="clear">清除筛选</button></div></div>
        </template>
        <div ref="more" v-show="!loading && !error && data && visibleCount < data.eggs.length" class="empty-hint" role="status">正在加载更多…</div>
      </div>
    </section>
    <div v-if="egg && modal" class="detail-backdrop" @click="close()"></div>
    <aside v-if="egg" id="ed-detail" class="detail-panel detail-open" :role="modal ? 'dialog' : 'region'" :aria-modal="modal || undefined" :aria-label="`${egg.egg_name}详情`">
      <button ref="closeButton" type="button" class="ghost-button small detail-close" @click="close()"><UiIcon name="x" />关闭详情</button>
      <EggDetail :egg="egg" />
    </aside>
  </div>
</template>
