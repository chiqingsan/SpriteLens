<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { HandbookSpecies } from '../types/handbook'
import DexPortrait from './DexPortrait.vue'
import DexTypeBadge from './DexTypeBadge.vue'
import DexMatchups from './DexMatchups.vue'
import DexRadar from './DexRadar.vue'
import DexGender from './DexGender.vue'
import DexRanges from './DexRanges.vue'
import UiIcon from './UiIcon.vue'
const { item } = defineProps<{ item: HandbookSpecies }>()
const emit = defineEmits<{ navigate: [key: string | number]; filterGroup: [group: string] }>()
const familyRoot = ref<HTMLElement | null>(null)
let familyDrag: { pointerId: number; startX: number; startScrollLeft: number; moved: boolean; container: HTMLElement } | null = null
let suppressFamilyClick = false
const dexText = computed(() => item.handbook_no || item.dex_no || '—')
const displayName = computed(() => item.display_name || item.name)
const stage = computed(() => ({ 1: 'I阶', 2: 'II阶', 3: 'III阶', 4: '最终形态' })[item.stage] || '阶段未知')
const form = computed(() => displayName.value.match(/[（(](.*)[）)]/)?.[1] || stage.value)
const chain = computed(() => item.chain_members.length ? item.chain_members : item.evolutions)
function displayGroup(group: string) { return group === '未发现' ? '蛋组未知' : group }
function familyPointerDown(event: PointerEvent) {
  const container = event.currentTarget as HTMLElement
  if (event.pointerType !== 'mouse' || event.button !== 0 || container.scrollWidth <= container.clientWidth) return
  event.preventDefault()
  container.setPointerCapture(event.pointerId)
  container.classList.add('dragging')
  familyDrag = { pointerId: event.pointerId, startX: event.clientX, startScrollLeft: container.scrollLeft, moved: false, container }
}
function familyPointerMove(event: PointerEvent) {
  if (!familyDrag || familyDrag.pointerId !== event.pointerId) return
  const distance = event.clientX - familyDrag.startX
  if (Math.abs(distance) > 4) familyDrag.moved = true
  event.preventDefault()
  familyDrag.container.scrollLeft = familyDrag.startScrollLeft - distance
}
function familyPointerEnd(event: PointerEvent) {
  if (!familyDrag || familyDrag.pointerId !== event.pointerId) return
  suppressFamilyClick = familyDrag.moved
  familyDrag.container.classList.remove('dragging')
  familyDrag = null
}
function familySelect(key: string | number, event: MouseEvent) {
  event.stopPropagation()
  if (suppressFamilyClick) {
    event.preventDefault()
    suppressFamilyClick = false
    return
  }
  emit('navigate', key)
}
function keepFamilyCurrentVisible() {
  const container = familyRoot.value?.querySelector<HTMLElement>('.mini-family-members')
  if (!container) return
  container.classList.toggle('is-scrollable', container.scrollWidth > container.clientWidth)
  const current = container.querySelector<HTMLElement>('[aria-current="true"]')
  if (!current) return
  const bounds = current.getBoundingClientRect()
  const viewport = container.getBoundingClientRect()
  if (bounds.left < viewport.left) container.scrollLeft -= viewport.left - bounds.left
  else if (bounds.right > viewport.right) container.scrollLeft += bounds.right - viewport.right
}
function syncFamilyScroll() { void nextTick(keepFamilyCurrentVisible) }
watch([() => item.key, chain], syncFamilyScroll)
onMounted(() => { keepFamilyCurrentVisible(); window.addEventListener('resize', keepFamilyCurrentVisible) })
onBeforeUnmount(() => window.removeEventListener('resize', keepFamilyCurrentVisible))
</script>
<template>
  <div class="dex-mini">
    <section class="handbook-detail-hero" :aria-label="`${displayName}资料`">
      <DexPortrait :src="item.artwork_url || item.icon_url" :name="displayName" eager />
      <div class="handbook-detail-art-top"><div class="handbook-detail-art-heading"><div class="handbook-detail-art-title"><h3>{{ displayName }}</h3><small>No.{{ dexText }}</small></div><b>{{ stage }}</b></div>
        <div class="handbook-detail-art-meta"><div class="handbook-detail-types"><DexTypeBadge v-for="(name, index) in item.type_names" :key="name" :name="name" :color="item.type_colors[index]" :icon-url="item.type_icons?.[name]" /></div></div>
      </div>
      <div class="handbook-detail-art-groups"><small>蛋组</small><button v-for="group in item.egg_groups" :key="group" @click="emit('filterGroup', group)">{{ displayGroup(group) }}</button><span v-if="!item.egg_groups.length">暂无蛋组</span></div>
      <div class="handbook-detail-art-shiny"><small>形态 · {{ form }}</small><b>异色 · {{ item.has_shiny ? '有异色' : '无异色' }}</b></div>
    </section>
    <section v-if="item.egg" class="handbook-detail-summary" aria-label="图鉴摘要">
      <button v-if="item.egg" class="handbook-related-entry" data-goto-page="egg-dex" :data-catalog-id="item.egg.egg_conf_id" :title="`${item.egg.name} · ${item.egg.hatch_label}`"><DexPortrait :src="item.egg.icon_url || ''" :name="item.egg.name" /><span><small>对应精灵蛋 · {{ item.egg.hatch_label }}</small><b>{{ item.egg.name }}</b><i>打开蛋图鉴 <UiIcon name="chevron-right" /></i></span></button>
    </section>
    <section class="mini-panel mini-stats"><header><h4>种族值</h4><span>总和 <b>{{ item.stat_sum || '—' }}</b></span></header>
      <div class="mini-stats-layout"><div class="mini-radar-box"><DexRadar :stats="item.stats" /></div><div class="mini-stats-side"><section class="mini-feature"><h4>特性</h4><b>{{ item.wiki?.feature?.name || '暂无数据' }}</b><p>{{ item.wiki?.feature?.description || '该精灵暂未收录特性资料' }}</p></section><DexGender :male="item.gender_ratio[0]" :female="item.gender_ratio[1]" /></div></div>
    </section>
    <DexMatchups :matchups="item.matchups" :icons="item.type_icons" />
    <DexRanges :ranges="item.reference_ranges" :areas="item.wiki?.areas" />
    <section ref="familyRoot" class="mini-panel mini-family"><h4>进化链 <small>点击精灵查看图鉴</small></h4><div class="mini-family-members" tabindex="0" aria-label="精灵进化链，可按住鼠标拖动横向滚动" @pointerdown="familyPointerDown" @pointermove="familyPointerMove" @pointerup="familyPointerEnd" @pointercancel="familyPointerEnd" @lostpointercapture="familyPointerEnd"><button v-for="(member, index) in chain" :key="member.key" :class="{ active: String(member.key) === item.key }" :aria-current="String(member.key) === item.key ? 'true' : undefined" @click.stop="familySelect(member.key, $event)"><small>{{ index + 1 }}</small><DexPortrait :src="member.icon_url || (String(member.key) === item.key ? item.icon_url : '')" :name="member.name" /><i>{{ member.stage ? member.stage === 1 ? '初始' : `第${member.stage}阶` : '关联形态' }}</i><span>{{ member.name }}</span></button><p v-if="!chain.length" class="muted">暂无进化记录</p></div><p class="mini-note">关联形态含分支，不表示依次进化。</p></section>
    <details v-if="item.wiki?.evolutions.length" class="mini-panel mini-extra"><summary>进化条件</summary><div v-for="branch in item.wiki.evolutions" :key="branch.name" class="wiki-source-card"><strong>{{ branch.name }}</strong><p v-for="member in branch.members" :key="member.name">{{ member.name }} · {{ [member.level ? `Lv.${member.level}` : '', member.condition, member.item].filter(Boolean).join(' / ') || '初始形态或条件未收录' }}</p></div></details>
    <footer class="mini-source"><span v-if="item.wiki">B站Wiki · </span><a :href="item.wiki?.source_url || `https://wiki.biligame.com/nrc/${encodeURIComponent(item.name)}`" target="_blank" rel="noopener noreferrer">查阅原始条目 <UiIcon name="chevron-right" /></a></footer>
  </div>
</template>
