<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { useHome, type HomeHost } from '../composables/useHome'
import PageShell from '../components/PageShell.vue'
import UiIcon from '../components/UiIcon.vue'
import type { HomeCouple, HomeResident } from '../types/home'
import './home.css'

const props = defineProps<{ host: HomeHost }>()
const model = useHome(props.host)
const failedImages = ref(new Set<string>())
const visibleMedalNames = new Set(['大块头', '小不点', '婉转声', '粗嗓门'])
const medalIds: Record<string, number> = { '大块头': 1001, '小不点': 1002, '婉转声': 1026, '粗嗓门': 1025 }
const homeSprites = computed(() => model.data.value?.residents || [])
const homeCouples = computed(() => model.data.value?.couples || [])
const nests = computed(() => model.data.value?.nests || [])
const sceneEggCount = computed(() => model.data.value?.scene_eggs.length || 0)
const couplesStale = computed(() => Boolean(model.data.value?.couples_stale))
const sortMode = ref<'level' | 'nature' | 'name'>('level')
const searchText = ref('')
const pairingGroups = computed(() => {
  const groups = new Map<string, HomeCouple[]>()
  homeCouples.value.forEach(couple => groups.set(couple.female_actor_id,
    [...(groups.get(couple.female_actor_id) || []), couple]))
  return [...groups.values()].sort((left, right) =>
    Number(right.some(couple => couple.mode !== 'ordinary'))
    - Number(left.some(couple => couple.mode !== 'ordinary')))
})
const filteredSprites = computed(() => {
  const query = searchText.value.toLowerCase()
  const rows = homeSprites.value.filter(resident => !query
    || [resident.name, resident.species_name, resident.nature_name]
      .some(text => (text || '').toLowerCase().includes(query)))
  const sorted = [...rows]
  const byName = (left: HomeResident, right: HomeResident) =>
    left.name.localeCompare(right.name, 'zh-Hans-CN')
  if (sortMode.value === 'name') sorted.sort(byName)
  else if (sortMode.value === 'nature') {
    sorted.sort((left, right) => (left.nature_name || '')
      .localeCompare(right.nature_name || '', 'zh-Hans-CN') || byName(left, right))
  } else {
    sorted.sort((left, right) => right.level - left.level || byName(left, right))
  }
  return sorted
})
watch(() => model.data.value?.uid, () => {
  failedImages.value = new Set()
})
onUnmounted(model.pause)

function genderLabel(gender: number) {
  return gender === 2 ? '雌' : gender === 1 ? '雄' : '未知'
}

function failedImage(actorId: string) {
  failedImages.value = new Set(failedImages.value).add(actorId)
}

function portraitMedals(resident: HomeResident) {
  return resident.medals.filter(mark => visibleMedalNames.has(mark.name))
}

function rarityIconUrl(resident: HomeResident) {
  if (resident.is_colorful) return resident.is_shiny
    ? '/static/rarity/shiny-colorful-fit.webp'
    : '/static/rarity/colorful-fit.webp'
  return resident.is_shiny ? '/static/rarity/shiny-fit.webp' : ''
}

function speciesLabel(resident: HomeResident) {
  return resident.species_name && resident.species_name !== resident.name ? resident.species_name : ''
}

function pairingModeLabel(group: HomeCouple[]) {
  return group.some(couple => couple.mode !== 'ordinary') ? '学院配对' : '普通配对'
}

function pairingBasisLabel(group: HomeCouple[]) {
  return group.some(couple => couple.pairing_basis === 'scene') ? '场景观察' : '小窝范围'
}

function residentFor(actorId: string) {
  return homeSprites.value.find(row => row.actor_id === actorId)
}

function fathersFor(group: HomeCouple[]) {
  const fathers = new Map<string, { actorId: string; name: string; voice: number | null }>()
  for (const couple of group) {
    couple.male_actor_ids.forEach((actorId, index) => {
      const prediction = couple.voice_predictions.find(row => row.father_actor_id === actorId)
      fathers.set(actorId, {
        actorId,
        name: couple.male_names[index] || '资料缺失',
        voice: prediction?.voice ?? null,
      })
    })
  }
  return [...fathers.values()]
}

function eggWeightText(actorId: string) {
  const range = residentFor(actorId)?.egg_weight_range
  if (!range) return '待确认'
  return `${(range.min / 1000).toFixed(2)}~${(range.max / 1000).toFixed(2)} kg`
}

function voiceRangeText(group: HomeCouple[]) {
  const values = group.flatMap(couple => couple.voice_predictions.map(row => row.voice))
    .filter((voice): voice is number => voice !== null)
  if (!values.length) return '待确认'
  const low = Math.min(...values), high = Math.max(...values)
  return low === high ? `${low} dB` : `${low}~${high} dB`
}

function startFatherDrag(event: PointerEvent) {
  if (event.button !== 0) return
  const row = event.currentTarget as HTMLElement
  event.preventDefault()
  row.setPointerCapture(event.pointerId)
  row.dataset.dragStartX = String(event.clientX)
  row.dataset.dragStartScroll = String(row.scrollLeft)
  row.classList.add('dragging')
}

function moveFatherDrag(event: PointerEvent) {
  const row = event.currentTarget as HTMLElement
  if (!row.hasPointerCapture(event.pointerId)) return
  row.scrollLeft = Number(row.dataset.dragStartScroll) - (event.clientX - Number(row.dataset.dragStartX))
}

function stopFatherDrag(event: PointerEvent) {
  const row = event.currentTarget as HTMLElement
  if (row.hasPointerCapture(event.pointerId)) row.releasePointerCapture(event.pointerId)
  row.classList.remove('dragging')
}

function naturePredictionRows(couple: HomeCouple) {
  const prediction = couple.nature_prediction
  return [
    ...Object.entries(prediction.distribution).map(([name, percent]) => ({ name, percent })),
    ...(prediction.random_percent > 0 ? [{ name: '随机', percent: prediction.random_percent }] : []),
    ...(prediction.unknown_percent > 0 ? [{ name: '待确认', percent: prediction.unknown_percent }] : []),
  ]
}

function percentText(value: number) {
  return `${Number(value.toFixed(2))}%`
}

function compactMeasure(text: string) {
  return text ? text.replace(/\s+(m|kg|dB)$/, '$1') : ''
}

function measurementPercent(ratio: number | null) {
  return ratio === null ? '—' : `${Math.round(Math.max(0, Math.min(1, ratio)) * 100)}%`
}

function ratioStyle(ratio: number | null) {
  if (ratio === null) return '0%'
  return `${Math.round(Math.max(0, Math.min(1, ratio)) * 100)}%`
}

function voiceRatio(resident: HomeResident) {
  return resident.voice === null ? null : (resident.voice + 100) / 200
}

function resetAccount() {
  model.resetAccount()
}

defineExpose({ load: model.load, resume: model.resume, pause: model.pause, resetAccount })
</script>

<template>
  <PageShell class="home-page" data-vue-page>
    <template #toolbar>
      <div class="home-toolbar">
        <div class="home-summary" aria-label="家园概览">
          <span class="home-summary-item">
            <UiIcon name="users" /><b>{{ homeSprites.length }}</b><span>只精灵</span>
          </span>
          <span class="home-summary-item">
            <UiIcon name="home" /><b>{{ nests.length }}</b><span>个小窝</span>
          </span>
          <span class="home-summary-item">
            <UiIcon name="arrows-shuffle" /><b>{{ pairingGroups.length }}</b><span>个母本</span>
          </span>
          <span v-if="sceneEggCount" class="home-summary-item">
            <UiIcon name="egg" /><b>{{ sceneEggCount }}</b><span>枚场景蛋</span>
          </span>
          <span v-if="couplesStale" class="home-summary-item is-stale">
            <UiIcon name="clock" /><span>关系待刷新</span>
          </span>
        </div>
        <div class="home-tools">
          <select v-model="sortMode" class="home-sort" aria-label="精灵排序">
            <option value="level">等级优先</option>
            <option value="nature">按性格</option>
            <option value="name">按名字</option>
          </select>
          <label class="home-search">
            <UiIcon name="search" />
            <input v-model.trim="searchText" type="search" placeholder="搜索名字 / 性格 / 物种" aria-label="搜索家园精灵">
          </label>
        </div>
      </div>
    </template>

    <div v-if="model.error.value" class="home-notice home-notice--error" role="alert">
      <span>读取家园失败：{{ model.error.value }}</span>
      <button type="button" @click="model.load()">重试</button>
    </div>

    <div v-if="!model.data.value && model.loading.value" class="home-empty home-empty--loading" aria-live="polite">
      正在读取家园快照…
    </div>
    <div v-else-if="!model.data.value?.available" class="home-empty">
      <div class="home-empty-mark"><UiIcon name="home" /></div>
      <strong>还没有观察到家园快照</strong>
      <p>开始采集后进入游戏家园，收到场景数据后这里会显示家园精灵与配对关系。</p>
      <button type="button" :disabled="model.loading.value" @click="model.load()">{{ model.loading.value ? '读取中…' : '重新读取' }}</button>
    </div>

    <div v-else-if="model.data.value" class="home-layout">
      <section class="home-panel home-residents-panel">
        <header class="home-panel-heading">
          <div>
            <h2>家园精灵</h2>
            <span class="home-count">{{ filteredSprites.length }}<template v-if="filteredSprites.length !== homeSprites.length"> / {{ homeSprites.length }}</template> 只</span>
          </div>
          <span class="home-panel-hint">按快照顺序</span>
        </header>

        <div v-if="!filteredSprites.length" class="home-empty-inline">
          <strong>{{ homeSprites.length ? '没有匹配的精灵' : '当前快照没有家园精灵记录' }}</strong>
          <p v-if="homeSprites.length">换个关键词，或清空搜索再看。</p>
          <p v-else>进入家园并等待场景快照更新后再查看。</p>
        </div>

        <div v-else class="home-resident-grid">
          <article v-for="resident in filteredSprites" :key="resident.actor_id" class="home-resident-card"
            :class="`gender-${resident.gender}`">
            <div class="home-portrait">
              <img v-if="resident.icon_url && !failedImages.has(resident.actor_id)" class="home-resident-image"
                :src="resident.icon_url" alt="" loading="lazy" draggable="false" @error="failedImage(resident.actor_id)">
              <span v-else class="home-portrait-fallback">{{ genderLabel(resident.gender) }}</span>
            </div>
            <div class="home-resident-main">
              <div class="home-resident-title">
                <strong>{{ resident.name }}</strong>
                <span class="home-gender-dot" :class="`gender-${resident.gender}`" :title="genderLabel(resident.gender)" />
                <img v-if="rarityIconUrl(resident)" class="home-rarity-icon" :src="rarityIconUrl(resident)"
                  :alt="resident.is_colorful ? '异色炫彩' : '异色'" :title="resident.is_colorful ? '异色炫彩' : '异色'" draggable="false">
                <span class="home-level">Lv.{{ resident.level }}</span>
              </div>
              <div class="home-resident-meta">
                <span v-if="speciesLabel(resident)" class="home-resident-species">{{ speciesLabel(resident) }}</span>
                <span v-if="resident.nature_name" class="home-nature-chip">{{ resident.nature_name }}</span>
                <img v-for="mark in portraitMedals(resident)" :key="mark.name" class="home-medal-icon"
                  :src="`/static/medal-icons/${medalIds[mark.name]}.webp`" :alt="mark.name" :title="mark.name" draggable="false">
              </div>
              <div class="home-metrics">
                <span class="home-metric" :class="{ unknown: resident.height_pct === null }">
                  <span class="home-metric-label"><UiIcon name="ruler-2" />身高</span>
                  <span class="home-metric-value">{{ compactMeasure(resident.height_text) || measurementPercent(resident.height_pct) }}</span>
                  <i class="home-metric-track"><b :style="{ width: ratioStyle(resident.height_pct) }"></b></i>
                </span>
                <span class="home-metric" :class="{ unknown: resident.weight_pct === null }">
                  <span class="home-metric-label"><UiIcon name="weight" />体重</span>
                  <span class="home-metric-value">{{ compactMeasure(resident.weight_text) || measurementPercent(resident.weight_pct) }}</span>
                  <i class="home-metric-track"><b :style="{ width: ratioStyle(resident.weight_pct) }"></b></i>
                </span>
                <span class="home-metric" :class="{ unknown: resident.voice === null }"
                  :title="resident.voice === null ? '声音刻度 −100 至 100 dB' : `声音刻度 −100 至 100 dB；当前 ${resident.voice} dB`">
                  <span class="home-metric-label"><UiIcon name="activity" />声音</span>
                  <span class="home-metric-value">{{ resident.voice === null ? '—' : `${resident.voice}dB` }}</span>
                  <i class="home-metric-track"><b :style="{ width: ratioStyle(voiceRatio(resident)) }"></b></i>
                </span>
              </div>
            </div>
          </article>
        </div>
      </section>

      <aside class="home-side">
        <section class="home-panel home-breeding-panel">
          <header class="home-panel-heading">
            <div>
              <h2>家园配对关系</h2>
              <span class="home-count">{{ pairingGroups.length }} 个母本</span>
            </div>
            <span v-if="couplesStale" class="home-pending-tag">关系待刷新</span>
          </header>
          <div v-if="pairingGroups.length" class="home-couple-list">
            <article v-for="(group, groupIndex) in pairingGroups" :key="groupIndex" class="home-couple-card"
              :class="{ 'home-couple-card--academy': group.some(couple => couple.mode !== 'ordinary') }">
              <header class="home-couple-head">
                <span class="home-couple-avatar">
                  <img v-if="residentFor(group[0].female_actor_id)?.icon_url"
                    :src="residentFor(group[0].female_actor_id)?.icon_url" alt="">
                  <span v-else>♀</span>
                </span>
                <div class="home-couple-title">
                  <strong>{{ group[0].female_name }}</strong>
                  <span class="home-couple-tags">
                    <span class="home-tag home-tag--mode">{{ pairingModeLabel(group) }}</span>
                    <span class="home-tag">{{ pairingBasisLabel(group) }}</span>
                  </span>
                </div>
              </header>
              <div class="home-couple-fathers">
                <span class="home-couple-label">父本</span>
                <div class="home-father-strip" @pointerdown="startFatherDrag" @pointermove="moveFatherDrag"
                  @pointerup="stopFatherDrag" @pointercancel="stopFatherDrag" @lostpointercapture="stopFatherDrag">
                  <span v-for="father in fathersFor(group)" :key="father.actorId" class="home-father" :title="father.name">
                    <img v-if="residentFor(father.actorId)?.icon_url" :src="residentFor(father.actorId)?.icon_url" alt="">
                    <span v-else class="home-father-fallback">♂</span>
                    <span class="home-father-name">{{ father.name }}</span>
                  </span>
                  <span v-if="!fathersFor(group).length" class="home-couple-missing">父本尚未识别</span>
                </div>
              </div>
              <div class="home-couple-egg">
                <span class="home-couple-label">生蛋</span>
                <img v-if="residentFor(group[0].female_actor_id)?.egg_icon_url" class="home-egg-icon"
                  :src="residentFor(group[0].female_actor_id)?.egg_icon_url" alt="">
                <strong>{{ residentFor(group[0].female_actor_id)?.egg_name || '蛋种待确认' }}</strong>
                <span class="home-couple-estimates">{{ eggWeightText(group[0].female_actor_id) }} · {{ voiceRangeText(group) }}</span>
              </div>
              <details v-for="(couple, coupleIndex) in group" :key="coupleIndex" class="home-couple-nature">
                <summary>
                  <UiIcon name="chevron-right" class="home-nature-chevron" />
                  <span>性格概率</span>
                  <span class="home-nature-count">{{ naturePredictionRows(couple).length }} 项</span>
                </summary>
                <div class="home-nature-list">
                  <div v-for="row in naturePredictionRows(couple)" :key="row.name" class="home-nature-item"
                    :class="`nature-${row.name === '随机' ? 'random' : row.name === '待确认' ? 'unknown' : 'known'}`"
                    :title="`${row.name} ${percentText(row.percent)}`">
                    <strong>{{ row.name }}</strong>
                    <span class="home-nature-track"><i :style="{ width: `${Math.max(0, Math.min(100, row.percent))}%` }"></i></span>
                    <span class="home-nature-percent">{{ percentText(row.percent) }}</span>
                  </div>
                </div>
              </details>
            </article>
          </div>
          <p v-else-if="couplesStale">家园变化后配对记录尚未刷新。</p>
          <p v-else>当前完整快照没有记录产蛋配对关系。</p>
        </section>
      </aside>
    </div>
  </PageShell>
</template>
