<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { collectionGoals, useCollectionLines, type CollectionHost } from '../composables/useCollectionLines'
import type { CollectionLine } from '../types/collectionLines'
import PageShell from '../components/PageShell.vue'
import PagePager from '../components/PagePager.vue'
import UiIcon from '../components/UiIcon.vue'
import CollectionParentCard from '../components/CollectionParentCard.vue'
import './collection-lines.css'

const props = defineProps<{ host: CollectionHost }>()
const model = useCollectionLines(props.host)
const { data, settings, loading, error, saveError } = model
const keyword = ref(''), group = ref(''), status = ref('all'), selected = ref(''), page = ref(1)
const labels = { collected: '已配齐', missingMale: '缺种公', missing: '未收集', unknown: '资料待补' }
const tabs = ['all', 'collected', 'missingMale', 'missing'] as const
const goalMedals: Record<string, number[]> = {
  'big-soft': [1001, 1026], 'big-loud': [1001, 1025], 'small-soft': [1002, 1026], 'small-loud': [1002, 1025],
}
const goalLabel = computed(() => collectionGoals.find(([key]) => key === settings.value.goal)?.[1])
const groups = computed(() => [...new Set(data.value?.lines.flatMap(line => line.groups) || [])].sort())
const rows = computed(() => {
  const search = keyword.value.trim().toLowerCase()
  return (data.value?.lines || []).filter(line => (status.value === 'all' || line.status === status.value)
    && (!group.value || line.groups.includes(group.value))
    && (!search || line.members.some(member => `${member.name} ${member.dex_no} ${member.base_id}`.toLowerCase().includes(search))))
})
const pages = computed(() => Math.max(1, Math.ceil(rows.value.length / 24)))
const visible = computed(() => rows.value.slice((page.value - 1) * 24, page.value * 24))
const detail = computed(() => data.value?.lines.find(line => line.key === selected.value))
const fathers = computed(() => new Map(data.value?.fathers.map(father => [father.gid, father]) || []))
const failed = ref(new Set<string>())
const narrow = window.matchMedia('(max-width: 960px)')
const isNarrow = ref(narrow.matches), filtersOpen = ref(false)
const side = ref<HTMLElement>(), closeButton = ref<HTMLButtonElement>(), detailBody = ref<HTMLElement>()
let trigger: HTMLElement | null = null
let inertNodes: HTMLElement[] = []
let active = true

watch([keyword, group, status], () => { page.value = 1 })
watch(pages, count => { page.value = Math.min(page.value, count) })
watch(() => data.value?.uid, () => { selected.value = ''; failed.value = new Set() })
watch([() => Boolean(detail.value), isNarrow], () => {
  syncModal()
  void nextTick(() => {
    if (detail.value && isNarrow.value) closeButton.value?.focus()
  })
})
watch(() => detail.value?.key, () => {
  void nextTick(() => { if (detailBody.value) detailBody.value.scrollTop = 0 })
})
function natures(line: CollectionLine) {
  return data.value?.natures.filter(nature => line.mothers.some(mother => mother.nature === nature
    && line.pairs.some(pair => pair.mother_gid === mother.gid && pair.father_gids.length))) || []
}
function fatherCount(line: CollectionLine) { return new Set(line.pairs.flatMap(pair => pair.father_gids)).size }
function open(line: CollectionLine, event: MouseEvent) {
  trigger = event.currentTarget instanceof HTMLElement ? event.currentTarget : null
  selected.value = line.key
}
async function close() {
  selected.value = ''
  await nextTick()
  trigger?.focus({ preventScroll: true })
}
function syncModal() {
  inertNodes.forEach(node => { node.inert = false })
  inertNodes = []
  if (active && detail.value && isNarrow.value) {
    inertNodes = [...document.querySelectorAll<HTMLElement>('.sidebar, .topbar, .collection-list-panel')]
    inertNodes.forEach(node => { node.inert = true })
  }
}
function resize() { isNarrow.value = narrow.matches; syncModal() }
function keydown(event: KeyboardEvent) {
  if (!active || !detail.value) return
  if (event.key === 'Escape') { event.preventDefault(); void close() }
  if (isNarrow.value && event.key === 'Tab') {
    const nodes = [...side.value!.querySelectorAll<HTMLElement>('button:not(:disabled), summary, [tabindex="0"]')]
      .filter(node => node.getClientRects().length)
    const first = nodes[0], last = nodes.at(-1)
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
  }
}
function pause() { active = false; syncModal(); model.pause() }
function load() { active = true; syncModal(); return model.load() }
function resetAccount() {
  model.resetAccount(); selected.value = ''; keyword.value = ''; group.value = ''; status.value = 'all'; page.value = 1
  filtersOpen.value = false; syncModal()
}
function clearFilters() { keyword.value = ''; group.value = ''; status.value = 'all' }
function showFilters() {
  selected.value = ''
  filtersOpen.value = !filtersOpen.value
}
onMounted(() => { narrow.addEventListener('change', resize); document.addEventListener('keydown', keydown) })
onUnmounted(() => {
  pause(); narrow.removeEventListener('change', resize); document.removeEventListener('keydown', keydown)
})
defineExpose({ load, pause, resetAccount })
</script>

<template>
  <PageShell class="collection-page" :class="{ 'filters-expanded': isNarrow && filtersOpen && !detail }">
    <template #toolbar>
        <div class="collection-overview">
          <span class="count-badge"><UiIcon name="checklist" />{{ settings.ignore_missing_male ? '种母收集' : '产线配齐' }} <b>{{ data?.totals.complete ?? '—' }}<span> / {{ data?.totals.eligible ?? '—' }}</span></b></span>
        </div>
        <div class="collection-controls">
          <label class="collection-search"><UiIcon name="search" /><input v-model="keyword" type="search" placeholder="搜索精灵 / 图鉴编号" aria-label="搜索进化链"></label>
          <button class="ghost-button small collection-filter-toggle" :class="{ active: filtersOpen && isNarrow }" :aria-expanded="isNarrow ? filtersOpen : undefined" @click="showFilters"><UiIcon name="adjustments" /><span>筛选条件</span></button>
          <button class="ghost-button small collection-refresh" :disabled="loading" aria-label="刷新产线记录" title="刷新记录" @click="model.load"><UiIcon name="refresh" /></button>
          <PagePager class="collection-pager" :page="page" :pages="pages" :page-size="24" unit="条" label="产线页码" @update:page="page = $event" />
        </div>
      </template>
    <div class="collection-body">
    <section class="collection-list-panel" :aria-busy="loading">
      
      <nav class="collection-tabs" aria-label="产线状态"><button v-for="tab in tabs" :key="tab" :class="{ active: status === tab }" :aria-pressed="status === tab" @click="status = tab">
        {{ tab === 'all' ? '全部' : labels[tab] }} <span>{{ tab === 'all' ? data?.lines.length ?? '—' : data?.totals[tab] ?? '—' }}</span></button></nav>
      <div class="collection-list-caption" :class="{ 'has-error': error || saveError }" role="status">
        <span v-if="error" :title="error">更新失败{{ data ? '，保留上次结果' : '' }}：{{ error }}</span>
        <span v-else-if="saveError" :title="saveError">{{ saveError }}</span>
        <span v-else-if="loading && !data">正在读取产线记录…</span>
        <span v-else>{{ goalLabel }}<i>·</i>{{ data?.pet_count ?? '—' }} 只{{ data?.source === 'history' ? '历史' : '观察' }}记录</span>
        <button v-if="error || saveError" class="text-button" @click="error ? model.load() : model.apply()">重试</button>
        <span v-else class="collection-match-count">命中 {{ rows.length }} 条</span>
      </div>
      <div class="collection-grid">
        <button v-for="line in visible" :key="line.key" class="collection-card" :class="{ selected: selected === line.key }" :aria-pressed="selected === line.key" @click="open(line, $event)">
          <div class="collection-card-topline"><span class="collection-card-groups" :title="line.groups.join(' / ')">{{ line.groups.join(' / ') }}</span><span class="collection-status" :class="line.status"><UiIcon v-if="line.status === 'collected'" name="circle-check" />{{ labels[line.status] }}</span></div>
          <div class="collection-card-portrait"><img v-if="line.members[0]?.icon_url && !failed.has(line.key)" :src="line.members[0].icon_url" alt="" loading="lazy" decoding="async" @error="failed.add(line.key)"><span v-else>{{ line.members[0]?.name.slice(0, 1) || '?' }}</span><small class="collection-card-dex">#{{ line.members[0]?.dex_no || '—' }}</small></div>
          <strong class="collection-card-name"><span :title="line.members[0]?.name">{{ line.members[0]?.name || '未知链' }}</span></strong>
          <div class="collection-natures"><span v-for="nature in natures(line).slice(0, 3)" :key="nature">{{ nature }}</span><span v-if="natures(line).length > 3" class="collection-natures-more" :title="natures(line).join('、')">+{{ natures(line).length - 3 }}</span><small v-if="!natures(line).length">{{ line.status === 'unknown' ? '进化链资料待补' : line.mothers.length ? '等待兼容种公' : '暂无目标种母' }}</small></div>
          <div class="collection-card-counts"><span><UiIcon name="gender-female" />种母 <b>{{ line.mothers.length }}</b></span><span><UiIcon name="gender-male" />种公 <b>{{ fatherCount(line) }}</b></span></div>
        </button>
        <div v-if="!visible.length" class="empty-hint collection-empty"><UiIcon :name="loading ? 'clock' : 'search'" /><strong>{{ loading && !data ? '正在读取产线记录…' : data && !data.available ? '可繁育目录尚未加载' : data?.lines.length ? '没有符合条件的产线' : '暂无产线数据' }}</strong><button v-if="data?.lines.length" class="ghost-button small" @click="clearFilters"><UiIcon name="filter-off" />清除筛选</button></div>
      </div>
    </section>

    <div v-if="detail && isNarrow" class="collection-backdrop" @click="close"></div>
    <aside v-show="!isNarrow || detail || filtersOpen" ref="side" class="collection-side" :class="{ 'showing-detail': detail, 'mobile-filters': isNarrow && !detail }" :role="detail && isNarrow ? 'dialog' : 'region'" :aria-modal="detail && isNarrow || undefined" :aria-label="detail ? '产线详情' : '产线筛选条件'">
      <template v-if="detail">
        <header class="collection-side-header"><h2>产线详情</h2><button ref="closeButton" class="ghost-button small" aria-label="关闭产线详情" @click="close"><UiIcon name="x" />关闭</button></header>
        <div ref="detailBody" class="collection-side-body">
          <section class="collection-detail-hero"><div class="collection-detail-title"><strong>{{ detail.members[0]?.name }}<small>#{{ detail.members[0]?.dex_no }}</small></strong><span class="collection-status" :class="detail.status">{{ labels[detail.status] }}</span></div><p>{{ detail.groups.join(' / ') }}</p>
            <div class="collection-members"><div v-for="(member, index) in detail.members" :key="member.base_id"><UiIcon v-if="index" name="chevron-right" /><div><img v-if="member.icon_url" :src="member.icon_url" alt="" loading="lazy"><span>{{ member.name }}</span></div></div></div>
          </section>
          <div class="collection-detail-summary"><span><UiIcon name="gender-female" />目标种母 <b>{{ detail.mothers.length }}</b></span><span><UiIcon name="gender-male" />兼容种公 <b>{{ fatherCount(detail) }}</b></span></div>
          <p v-for="gap in detail.gaps" :key="gap" class="collection-gap">{{ gap }}</p>
          <div v-if="!detail.mothers.length" class="empty-hint collection-detail-empty"><UiIcon name="search" /><strong>暂无目标种母</strong><span>采集背包与仓库后，符合目标的种母将显示在这里。</span></div>
          <section v-for="mother in detail.mothers" :key="mother.gid" class="collection-pair">
            <h3><span class="collection-nature-label">{{ mother.nature }}</span><span>亲本候选</span></h3>
            <CollectionParentCard :parent="mother" @open="host.openPet" />
            <template v-for="pair in detail.pairs.filter(pair => pair.mother_gid === mother.gid)" :key="pair.mother_gid">
              <div class="collection-pair-link"><UiIcon name="users" /><span>{{ pair.father_gids.length ? `兼容种公 ${pair.father_gids.length} 只` : '缺少兼容种公' }}</span></div>
              <p v-if="!pair.father_gids.length" class="collection-pair-empty">需要同双牌、{{ mother.nature }}性格，且蛋组相容的雄性。</p>
              <template v-for="gid in pair.father_gids" :key="gid"><CollectionParentCard v-if="fathers.get(gid)" :parent="fathers.get(gid)!" @open="host.openPet" /></template>
            </template>
          </section>
        </div>
      </template>
      <template v-else>
        <header class="collection-side-header"><h2>筛选产线</h2><button class="ghost-button small" @click="clearFilters"><UiIcon name="filter-off" />重置筛选</button></header>
        <div class="collection-side-body collection-filters">
          <section class="direct-filter"><h3>双牌目标</h3><div class="collection-goals"><button v-for="[key, label] in collectionGoals" :key="key" class="chip" :class="{ active: settings.goal === key }" :aria-pressed="settings.goal === key" @click="settings.goal = key; model.apply()"><span><img v-for="medal in goalMedals[key]" :key="medal" :src="`/static/medal-icons/${medal}.webp`" alt=""></span>{{ label }}</button></div><p class="collection-rule-note">按体重与声音标记统计，满身高不替代大块头；数值参考不等于已获奖牌。</p></section>
          <section class="collection-filter-section"><h3>蛋组</h3><div class="chip-group collection-group-options"><button class="chip" :class="{ active: !group }" :aria-pressed="!group" @click="group = ''">全部</button><button v-for="name in groups" :key="name" class="chip" :class="{ active: group === name }" :aria-pressed="group === name" @click="group = group === name ? '' : name">{{ name }}</button></div></section>
          <section class="collection-filter-section"><h3>声音条件</h3><div class="segmented collection-sound" role="group" aria-label="声音条件"><button v-for="[value, label] in [['', '不限'], ['100', '+100 dB'], ['-100', '−100 dB']]" :key="value" :class="{ active: settings.sound === value }" :aria-pressed="settings.sound === value" @click="settings.sound = value; model.apply()">{{ label }}</button></div></section>
          <section class="collection-filter-section"><h3>统计条件</h3><div class="collection-parent-options"><button v-for="[key, label, icon] in ([['full_weight', '仅满体重亲本', 'weight'], ['colorful', '仅炫彩亲本', 'palette'], ['ignore_missing_male', '忽略缺种公', 'gender-female']] as const)" :key="key" class="chip" :class="{ active: settings[key] }" :aria-pressed="settings[key]" @click="settings[key] = !settings[key]; model.apply()"><UiIcon :name="icon" />{{ label }}<UiIcon v-if="settings[key]" name="circle-check" /></button></div></section>
          <details class="collection-filter-section collection-rules"><summary>统计说明<UiIcon name="chevron-right" /></summary><p>本页收集同账号、同双标、同性格且蛋组相容的组合，统计全部已知性格。同性格是收集条件，不是生蛋前提。</p><p>体型、声音标记与背包使用同一规则；满身高不替代大块头，最低身高不替代小不点。数值参考不等于已获奖牌。</p><p>亲本配齐不代表已经配窝或子代必出双牌；观察记录可能含已移出个体，学院小窝另行验证。</p></details>
        </div>
      </template>
    </aside>
    </div>
  </PageShell>
</template>
