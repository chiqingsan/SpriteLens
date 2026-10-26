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
const roomLevel = computed(() => model.data.value?.room_level || 0)
const sceneEggCount = computed(() => model.data.value?.scene_eggs.length || 0)
const couplesStale = computed(() => Boolean(model.data.value?.couples_stale))
const academyResidentIds = computed(() => {
  const ids = new Set<string>()
  nests.value.forEach(nest => {
    if (nest.kind !== 'academy') return
    nest.resident_ids.forEach(id => ids.add(String(id)))
  })
  return ids
})
function isAcademy(resident: HomeResident) {
  if (academyResidentIds.value.has(String(resident.actor_id))) return true
  return nests.value.some(nest => nest.kind === 'academy' && nest.guid === resident.nest_guid)
}
const sortMode = ref<'level' | 'nature' | 'name'>('level')
const searchText = ref('')
const hoveredSprite = ref('')
const hoveredPairIds = ref<string[]>([])
function pairMemberIds(group: HomeCouple[]) {
  const ids = new Set<string>()
  group.forEach(couple => {
    ids.add(couple.female_actor_id)
    couple.male_actor_ids.forEach(id => ids.add(id))
  })
  return [...ids]
}
function pairLinked(group: HomeCouple[]) {
  if (!hoveredSprite.value) return false
  return group.some(couple => couple.female_actor_id === hoveredSprite.value
    || couple.male_actor_ids.includes(hoveredSprite.value))
}
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

const pairPalette = ['var(--teal-deep)', 'var(--amber-ink)', 'var(--male-ink)', 'var(--female-ink)']

function pairColor(index: number) {
  return pairPalette[index % pairPalette.length]
}

function naturePredictionRows(couple: HomeCouple) {
  const prediction = couple.nature_prediction
  return [
    ...Object.entries(prediction.distribution).map(([name, percent]) => ({ name, percent })),
    ...(prediction.random_percent > 0 ? [{ name: '随机', percent: prediction.random_percent }] : []),
    ...(prediction.unknown_percent > 0 ? [{ name: '待确认', percent: prediction.unknown_percent }] : []),
  ]
}

function natureRowsFor(group: HomeCouple[]) {
  return group.flatMap(couple => naturePredictionRows(couple))
    .sort((left, right) => right.percent - left.percent)
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
    <section class="home-hero" aria-labelledby="home-title">
      <div class="home-hero-copy">
        <span class="home-hero-eyebrow"><UiIcon name="home" />我的家园</span>
        <h1 id="home-title">
          <strong>{{ homeSprites.length || '—' }}</strong> 只精灵
          <span class="home-hero-sep">/</span>
          <strong>{{ nests.length || '—' }}</strong> 个小窝
        </h1>
        <p class="home-hero-sub">
          <template v-if="pairingGroups.length">{{ pairingGroups.length }} 个母本正在配对</template>
          <template v-else>还没有配对关系</template>
          <span class="home-hero-dot" aria-hidden="true">·</span>
          <span class="home-hero-state" :class="{ 'is-stale': couplesStale }">
            <UiIcon :name="couplesStale ? 'clock' : 'circle-check'" />
            {{ couplesStale ? '配对关系待刷新' : '快照已同步' }}
          </span>
        </p>
        <div class="home-hero-meta">
          <span class="home-meta-item"><UiIcon name="users" /><b>{{ homeSprites.length }}</b>精灵</span>
          <span class="home-meta-item"><UiIcon name="home" /><b>{{ nests.length }}</b>小窝</span>
          <span class="home-meta-item"><UiIcon name="arrows-shuffle" /><b>{{ pairingGroups.length }}</b>母本</span>
          <span class="home-meta-item"><UiIcon name="egg" /><b>{{ sceneEggCount }}</b>场景蛋</span>
        </div>
        <div class="home-hero-actions">
          <button type="button" class="home-ghost-button" :disabled="model.loading.value" @click="model.load()">
            <UiIcon name="refresh" />{{ model.loading.value ? '读取中…' : '刷新快照' }}
          </button>
        </div>
      </div>
      <div class="home-hero-level" :title="`房间等级 ${roomLevel}`" :aria-label="`房间等级 ${roomLevel}`">
        <span>房间等级</span>
        <strong>{{ roomLevel || '—' }}</strong>
      </div>
    </section>

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

    <template v-else-if="model.data.value">
      <div class="home-columns">
      <section class="home-section home-sprites" aria-labelledby="home-sprites-title">
        <header class="home-section-head">
          <div class="home-section-title">
            <h2 id="home-sprites-title">家园精灵</h2>
            <span class="home-count">{{ filteredSprites.length }}<template v-if="filteredSprites.length !== homeSprites.length"> / {{ homeSprites.length }}</template> 只</span>
          </div>
          <div class="home-section-tools">
            <select v-model="sortMode" class="home-sort" aria-label="精灵排序">
              <option value="level">等级优先</option>
              <option value="nature">按性格</option>
              <option value="name">按名字</option>
            </select>
            <label class="home-search">
              <UiIcon name="search" />
              <input v-model.trim="searchText" type="search" placeholder="搜索精灵" aria-label="搜索家园精灵">
            </label>
          </div>
        </header>

        <div v-if="!filteredSprites.length" class="home-empty-inline">
          <strong>{{ homeSprites.length ? '没有匹配的精灵' : '当前快照没有家园精灵记录' }}</strong>
          <p v-if="homeSprites.length">换个关键词，或清空搜索再看。</p>
          <p v-else>进入家园并等待场景快照更新后再查看。</p>
        </div>

        <div v-else class="home-sprite-grid">
          <article v-for="resident in filteredSprites" :key="resident.actor_id" class="home-sprite-card"
            :class="[`gender-${resident.gender}`, { 'is-academy': isAcademy(resident), 'is-linked': hoveredPairIds.includes(resident.actor_id) }]"
            @mouseenter="hoveredSprite = resident.actor_id" @mouseleave="hoveredSprite = ''">
            <div class="home-sprite-art">
              <img v-if="resident.icon_url && !failedImages.has(resident.actor_id)" class="home-sprite-image"
                :src="resident.icon_url" alt="" loading="lazy" draggable="false" @error="failedImage(resident.actor_id)">
              <span v-else class="home-sprite-fallback">{{ genderLabel(resident.gender) }}</span>
              <span class="home-sprite-level">Lv.{{ resident.level }}</span>
              <img v-if="rarityIconUrl(resident)" class="home-sprite-rarity" :src="rarityIconUrl(resident)"
                :alt="resident.is_colorful ? '异色炫彩' : '异色'" :title="resident.is_colorful ? '异色炫彩' : '异色'" draggable="false">
              <span v-if="isAcademy(resident)" class="home-sprite-academy" title="学院绿窝精灵">
                <UiIcon name="graduation-cap" />学院
              </span>
            </div>
            <div class="home-sprite-body">
              <div class="home-sprite-title">
                <strong>{{ resident.name }}</strong>
                <span class="home-gender-dot" :class="`gender-${resident.gender}`" :title="genderLabel(resident.gender)" />
              </div>
              <div class="home-sprite-meta">
                <span v-if="speciesLabel(resident)" class="home-sprite-species">{{ speciesLabel(resident) }}</span>
                <span v-if="resident.nature_name" class="home-nature-chip">{{ resident.nature_name }}</span>
                <img v-for="mark in portraitMedals(resident)" :key="mark.name" class="home-medal-icon"
                  :src="`/static/medal-icons/${medalIds[mark.name]}.webp`" :alt="mark.name" :title="mark.name" draggable="false">
              </div>
              <div class="home-sprite-metrics">
                <span class="home-sprite-metric" :class="{ unknown: resident.height_pct === null }">
                  <span class="home-sprite-metric-label"><UiIcon name="ruler-2" />身高</span>
                  <span class="home-sprite-metric-value">{{ compactMeasure(resident.height_text) || measurementPercent(resident.height_pct) }}</span>
                  <i class="home-sprite-metric-track"><b :style="{ width: ratioStyle(resident.height_pct) }"></b></i>
                </span>
                <span class="home-sprite-metric" :class="{ unknown: resident.weight_pct === null }">
                  <span class="home-sprite-metric-label"><UiIcon name="weight" />体重</span>
                  <span class="home-sprite-metric-value">{{ compactMeasure(resident.weight_text) || measurementPercent(resident.weight_pct) }}</span>
                  <i class="home-sprite-metric-track"><b :style="{ width: ratioStyle(resident.weight_pct) }"></b></i>
                </span>
                <span class="home-sprite-metric" :class="{ unknown: resident.voice === null }"
                  :title="resident.voice === null ? '声音刻度 −100 至 100 dB' : `声音刻度 −100 至 100 dB；当前 ${resident.voice} dB`">
                  <span class="home-sprite-metric-label"><UiIcon name="activity" />声音</span>
                  <span class="home-sprite-metric-value">{{ resident.voice === null ? '—' : `${resident.voice}dB` }}</span>
                  <i class="home-sprite-metric-track"><b :style="{ width: ratioStyle(voiceRatio(resident)) }"></b></i>
                </span>
              </div>
            </div>
          </article>
        </div>
      </section>

      <aside class="home-side">
      <section class="home-section home-pairing" aria-labelledby="home-pairing-title">
        <header class="home-section-head">
          <div class="home-section-title">
            <h2 id="home-pairing-title">家园配对关系</h2>
            <span class="home-count">{{ pairingGroups.length }} 个母本</span>
          </div>
          <span v-if="couplesStale" class="home-pending-tag">关系待刷新</span>
        </header>

        <div v-if="pairingGroups.length" class="home-pairing-grid">
          <article v-for="(group, groupIndex) in pairingGroups" :key="groupIndex" class="home-pair-card"
            :class="{ 'home-pair-card--academy': group.some(couple => couple.mode !== 'ordinary'), 'is-linked': pairLinked(group) }"
            @mouseenter="hoveredPairIds = pairMemberIds(group)" @mouseleave="hoveredPairIds = []">
            <header class="home-pair-head">
              <span class="home-tag home-tag--mode">{{ pairingModeLabel(group) }}</span>
              <span class="home-tag">{{ pairingBasisLabel(group) }}</span>
            </header>
            <div class="home-pair-diagram" :style="{ '--pair-color': pairColor(groupIndex) }">
              <div class="home-pair-mother">
                <span class="home-pair-avatar">
                  <img v-if="residentFor(group[0].female_actor_id)?.icon_url"
                    :src="residentFor(group[0].female_actor_id)?.icon_url" alt="">
                  <span v-else>♀</span>
                </span>
                <span class="home-pair-mother-name">{{ group[0].female_name }}</span>
                <span class="home-pair-role-label">母本</span>
              </div>
              <div class="home-pair-branch">
                <span v-for="father in fathersFor(group)" :key="father.actorId" class="home-pair-father" :title="father.name">
                  <span class="home-pair-father-avatar">
                    <img v-if="residentFor(father.actorId)?.icon_url" :src="residentFor(father.actorId)?.icon_url" alt="">
                    <span v-else>♂</span>
                  </span>
                  <span class="home-pair-father-name">{{ father.name }}</span>
                  <span class="home-pair-father-role">父本</span>
                </span>
                <span v-if="!fathersFor(group).length" class="home-couple-missing">父本尚未识别</span>
              </div>
            </div>
            <div class="home-pair-egg">
              <span class="home-pair-label">生蛋</span>
              <img v-if="residentFor(group[0].female_actor_id)?.egg_icon_url" class="home-egg-icon"
                :src="residentFor(group[0].female_actor_id)?.egg_icon_url" alt="">
              <UiIcon v-else name="egg" class="home-egg-mark" />
              <strong>{{ residentFor(group[0].female_actor_id)?.egg_name || '蛋种待确认' }}</strong>
              <span class="home-pair-range">{{ eggWeightText(group[0].female_actor_id) }}</span>
              <span class="home-pair-range">{{ voiceRangeText(group) }}</span>
            </div>
            <details class="home-pair-nature">
              <summary>
                <span>性格概率</span>
                <span class="home-pair-nature-count">{{ natureRowsFor(group).length }} 项</span>
                <UiIcon name="chevron-right" class="home-nature-chevron" />
              </summary>
              <div class="home-nature-list">
                <span v-for="row in natureRowsFor(group)" :key="row.name" class="home-nature-item"
                  :class="{ 'nature-random': row.name === '随机', 'nature-unknown': row.name === '待确认' }">
                  <strong>{{ row.name }}</strong>
                  <span class="home-nature-track"><i :style="{ width: `${Math.max(4, Math.min(100, row.percent))}%` }"></i></span>
                  <span class="home-nature-percent">{{ percentText(row.percent) }}</span>
                </span>
              </div>
            </details>
          </article>
        </div>
        <div v-else class="home-empty-inline">
          <strong>暂时没有配对关系</strong>
          <p>把雌性精灵放进小窝，并让雄性精灵在同一区域活动，配对关系会出现在这里。</p>
        </div>
      </section>
      </aside>
      </div>
    </template>
  </PageShell>
</template>
