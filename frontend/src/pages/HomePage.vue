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
const pairingGroups = computed(() => {
  const groups = new Map<string, HomeCouple[]>()
  homeCouples.value.forEach(couple => groups.set(couple.female_actor_id,
    [...(groups.get(couple.female_actor_id) || []), couple]))
  return [...groups.values()].sort((left, right) =>
    Number(right.some(couple => couple.mode !== 'ordinary'))
    - Number(left.some(couple => couple.mode !== 'ordinary')))
})

interface NestGroup {
  guid: string | null
  name: string
  kind: 'ordinary' | 'academy'
  residents: HomeResident[]
}

const nestGroups = computed<NestGroup[]>(() => {
  const data = model.data.value
  if (!data) return []
  const groups: NestGroup[] = data.nests
    .map(nest => ({
      guid: nest.guid as string | null,
      name: nest.name,
      kind: nest.kind as 'ordinary' | 'academy',
      residents: homeSprites.value.filter(resident => resident.nest_guid === nest.guid),
    }))
    .filter(group => group.residents.length > 0)
  const placed = new Set(groups.flatMap(group => group.residents.map(resident => resident.actor_id)))
  const unplaced = homeSprites.value.filter(resident => !placed.has(resident.actor_id))
  if (unplaced.length) groups.push({ guid: null, name: '未归入小窝', kind: 'ordinary', residents: unplaced })
  return groups
})

interface PairFather {
  actorId: string
  name: string
  nature: string | null
  academy: boolean
}

interface PairNatureRow {
  name: string
  percent: number
  kind: 'known' | 'random' | 'unknown'
  percentText: string
}

interface PairGroup {
  key: string
  inferred: boolean
  academy: boolean
  motherActorId: string
  motherName: string
  motherNature: string | null
  eggName: string
  eggIcon: string
  eggWeight: string
  voiceRange: string
  fathers: PairFather[]
  natures: PairNatureRow[]
}

function buildGroups(couples: HomeCouple[], inferred: boolean): PairGroup[] {
  const buckets = new Map<string, HomeCouple[]>()
  couples.forEach(couple => buckets.set(couple.female_actor_id,
    [...(buckets.get(couple.female_actor_id) || []), couple]))
  return [...buckets.values()].map(group => {
    const first = group[0]
    const mother = residentFor(first.female_actor_id)
    const fathers: PairFather[] = []
    const seen = new Set<string>()
    group.forEach(couple => {
      couple.male_actor_ids.forEach((actorId, index) => {
        if (seen.has(actorId)) return
        seen.add(actorId)
        fathers.push({
          actorId,
          name: couple.male_names[index] || '资料缺失',
          nature: couple.male_natures[index] ?? null,
          academy: Boolean(couple.male_is_academy[index]),
        })
      })
    })
    const prediction = first.nature_prediction ?? { distribution: {}, random_percent: 0, unknown_percent: 0 }
    const natures: PairNatureRow[] = Object.entries(prediction.distribution || {})
      .sort((left, right) => right[1] - left[1])
      .slice(0, 5)
      .map(([name, percent]) => ({ name, percent, kind: 'known' as const, percentText: percentText(percent) }))
    if (prediction.random_percent > 0) {
      natures.push({ name: '随机', percent: prediction.random_percent, kind: 'random', percentText: percentText(prediction.random_percent) })
    }
    if (prediction.unknown_percent > 0) {
      natures.push({ name: '待确认', percent: prediction.unknown_percent, kind: 'unknown', percentText: percentText(prediction.unknown_percent) })
    }
    return {
      key: `${inferred ? 'inferred' : 'scene'}:${first.female_actor_id}`,
      inferred,
      academy: Boolean(first.female_is_academy) || first.male_is_academy.some(Boolean) || first.mode !== 'ordinary',
      motherActorId: first.female_actor_id,
      motherName: first.female_name,
      motherNature: first.female_nature,
      eggName: mother?.egg_name || '蛋种待确认',
      eggIcon: mother?.egg_icon_url || '',
      eggWeight: eggWeightText(first.female_actor_id),
      voiceRange: voiceRangeText(group),
      fathers,
      natures,
    }
  })
}

const relationGroups = computed<PairGroup[]>(() => {
  const data = model.data.value
  if (!data) return []
  const groups = [...buildGroups(data.couples, false), ...buildGroups(data.inferred_couples || [], true)]
  return groups.sort((left, right) =>
    Number(right.academy) - Number(left.academy) || left.motherName.localeCompare(right.motherName, 'zh'))
})

const statusTone = computed(() => {
  if (model.error.value) return 'is-bad'
  const data = model.data.value
  if (!data) return 'is-pending'
  return data.couples_stale ? 'is-warn' : 'is-ok'
})

const statusLabel = computed(() => {
  if (model.error.value) return '读取失败'
  const data = model.data.value
  if (!data) return '正在读取快照'
  if (!data.available) return '还没有快照'
  return data.couples_stale ? '关系待刷新' : '快照已同步'
})

const freshnessNote = computed(() => {
  const data = model.data.value
  if (!data) return ''
  if (data.pending_deltas) return `还有 ${data.pending_deltas} 条变化待合并`
  if (data.couples_stale) return '家园变动后配对关系待刷新'
  return '场景快照已同步'
})

const heroStats = computed(() => {
  const data = model.data.value
  return [
    { icon: 'users', label: '家园精灵', value: homeSprites.value.length },
    { icon: 'box', label: '小窝', value: data?.nests.length ?? 0 },
    { icon: 'arrows-shuffle', label: '配对母本', value: pairingGroups.value.length },
    { icon: 'egg', label: '场景蛋', value: data?.scene_eggs.length ?? 0 },
  ]
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

function residentFor(actorId: string) {
  return homeSprites.value.find(row => row.actor_id === actorId)
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

function percentText(value: number) {
  return `${Number(value.toFixed(2))}%`
}

function measurementPercent(ratio: number | null) {
  return ratio === null ? '—' : `${Math.round(Math.max(0, Math.min(1, ratio)) * 100)}%`
}

function meterWidth(ratio: number | null) {
  if (ratio === null) return '0%'
  return `${Math.round(Math.max(0, Math.min(1, ratio)) * 100)}%`
}

function voiceMeterWidth(voice: number | null) {
  if (voice === null) return '0%'
  return `${Math.round(Math.max(0, Math.min(1, (voice + 100) / 200)) * 100)}%`
}

function resetAccount() {
  model.resetAccount()
}

defineExpose({ load: model.load, resume: model.resume, pause: model.pause, resetAccount })
</script>

<template>
  <PageShell class="home-page" :busy="model.loading.value" data-vue-page>
    <template #toolbar>
      <div class="ui-page-heading">
        <span class="home-status" :class="statusTone"><i class="home-status-dot" />{{ statusLabel }}</span>
        <p class="ui-page-meta">
          房间等级 Lv.{{ model.data.value?.room_level ?? '—' }} · {{ homeSprites.length }} 名精灵 · {{ model.data.value?.nests.length ?? 0 }} 个小窝
        </p>
      </div>
      <div class="ui-page-actions">
        <button type="button" class="ghost-button small home-refresh" :disabled="model.loading.value" @click="model.load()">
          <UiIcon name="refresh" /><span>{{ model.loading.value ? '读取中…' : '刷新快照' }}</span>
        </button>
      </div>
    </template>

    <div v-if="model.error.value" class="home-notice home-notice--error" role="alert">
      <span>读取家园失败：{{ model.error.value }}</span>
      <button type="button" @click="model.load()">重试</button>
    </div>

    <div v-if="!model.data.value && model.loading.value" class="home-loading" aria-live="polite">
      <div class="home-skeleton-hero"><i /><i /><i /><i /></div>
      <div class="home-skeleton-grid">
        <div v-for="n in 4" :key="n" class="home-skeleton-card" />
      </div>
    </div>

    <div v-else-if="!model.data.value?.available" class="home-empty">
      <div class="home-empty-mark"><UiIcon name="home" /></div>
      <strong>还没有观察到家园快照</strong>
      <p>开始采集后进入游戏家园，收到场景数据后这里会显示家园精灵、小窝与配对关系。</p>
      <button type="button" class="primary-button" :disabled="model.loading.value" @click="model.load()">
        {{ model.loading.value ? '读取中…' : '重新读取' }}
      </button>
    </div>

    <template v-else-if="model.data.value">
      <section class="home-hero" aria-label="家园概览">
        <div class="home-hero-level">
          <span class="home-hero-level-label"><UiIcon name="home" />房间等级</span>
          <strong class="home-hero-level-value">{{ model.data.value.room_level }}</strong>
          <span class="home-hero-level-note">{{ freshnessNote }}</span>
          <UiIcon class="home-hero-watermark" name="home" />
        </div>
        <div v-for="stat in heroStats" :key="stat.label" class="home-stat">
          <span class="home-stat-icon"><UiIcon :name="stat.icon" /></span>
          <strong>{{ stat.value }}</strong>
          <span>{{ stat.label }}</span>
        </div>
      </section>

      <div class="home-layout">
        <section class="home-panel home-residents-panel">
          <header class="home-panel-head">
            <div>
              <h2>家园精灵</h2>
              <span class="home-panel-meta">{{ homeSprites.length }} 只 · 按小窝分组</span>
            </div>
          </header>
          <div v-if="homeSprites.length" class="home-nest-list">
            <section v-for="group in nestGroups" :key="group.guid || 'unplaced'" class="home-nest">
              <header class="home-nest-head">
                <span class="home-nest-name" :class="{ 'is-academy': group.kind === 'academy' }">
                  <UiIcon name="box" />{{ group.name }}
                </span>
                <span class="home-nest-meta">{{ group.residents.length }} 名</span>
              </header>
              <div class="home-resident-grid">
                <article
                  v-for="resident in group.residents"
                  :key="resident.actor_id"
                  class="home-resident-card"
                  :class="`gender-${resident.gender}`"
                >
                  <div class="home-resident-art">
                    <img
                      v-if="resident.icon_url && !failedImages.has(resident.actor_id)"
                      class="home-resident-image"
                      :src="resident.icon_url"
                      alt=""
                      loading="lazy"
                      draggable="false"
                      @error="failedImage(resident.actor_id)"
                    >
                    <span class="home-resident-level">Lv.{{ resident.level }}</span>
                    <span v-if="rarityIconUrl(resident)" class="home-resident-rarity">
                      <img
                        :src="rarityIconUrl(resident)"
                        :alt="resident.is_colorful ? '异色炫彩' : '异色'"
                        :title="resident.is_colorful ? '异色炫彩' : '异色'"
                        draggable="false"
                      >
                    </span>
                  </div>
                  <div class="home-resident-copy">
                    <div class="home-resident-title">
                      <strong>{{ resident.name }}</strong>
                      <span
                        class="home-gender"
                        :class="`gender-${resident.gender}`"
                        :aria-label="genderLabel(resident.gender)"
                        :title="genderLabel(resident.gender)"
                      >
                        <UiIcon v-if="resident.gender === 1 || resident.gender === 2" :name="resident.gender === 1 ? 'gender-male' : 'gender-female'" />
                        <span v-else class="home-gender-text">{{ genderLabel(resident.gender) }}</span>
                      </span>
                    </div>
                    <div class="home-resident-sub">{{ resident.species_name || '物种资料未收录' }}</div>
                    <div class="home-resident-chips">
                      <span v-if="resident.nature_name" class="home-chip">性格 {{ resident.nature_name }}</span>
                      <span v-if="resident.egg_groups.length" class="home-chip home-chip--quiet">蛋组 {{ resident.egg_groups.join(' · ') }}</span>
                      <img
                        v-for="mark in portraitMedals(resident)"
                        :key="mark.name"
                        class="home-medal"
                        :src="`/static/medal-icons/${medalIds[mark.name]}.webp`"
                        :alt="mark.name"
                        :title="mark.name"
                        draggable="false"
                      >
                    </div>
                    <div class="home-meters">
                      <span class="home-meter" :class="{ unknown: resident.height_pct === null }" :title="`身高 ${resident.height_text || '待确认'}`">
                        <UiIcon name="ruler-2" /><label>身高</label><i><b :style="{ width: meterWidth(resident.height_pct) }" /></i><em>{{ measurementPercent(resident.height_pct) }}</em>
                      </span>
                      <span class="home-meter" :class="{ unknown: resident.weight_pct === null }" :title="`体重 ${resident.weight_text || '待确认'}`">
                        <UiIcon name="weight" /><label>体重</label><i><b :style="{ width: meterWidth(resident.weight_pct) }" /></i><em>{{ measurementPercent(resident.weight_pct) }}</em>
                      </span>
                      <span class="home-meter" :class="{ unknown: resident.voice === null }" :title="resident.voice === null ? '声音刻度 −100 至 100 dB' : `声音刻度 −100 至 100 dB；当前 ${resident.voice} dB`">
                        <UiIcon name="activity" /><label>声音</label><i><b :style="{ width: voiceMeterWidth(resident.voice) }" /></i><em>{{ resident.voice === null ? '—' : measurementPercent((resident.voice + 100) / 200) }}</em>
                      </span>
                    </div>
                  </div>
                </article>
              </div>
            </section>
          </div>
          <div v-else class="home-inline-empty">
            <UiIcon name="users" />
            <strong>当前快照没有家园精灵记录</strong>
            <p>进入家园并等待场景快照更新后再查看。</p>
          </div>
        </section>

        <aside class="home-side">
          <section class="home-panel home-pairing-panel">
            <header class="home-panel-head">
              <div>
                <h2>配对关系</h2>
                <span class="home-panel-meta">{{ relationGroups.length }} 组</span>
              </div>
              <span v-if="model.data.value.couples_stale" class="home-pending-tag">关系待刷新</span>
            </header>
            <div v-if="relationGroups.length" class="home-pair-list">
              <article v-for="group in relationGroups" :key="group.key" class="home-pair">
                <header class="home-pair-head">
                  <span class="home-pair-mode" :class="{ 'is-academy': group.academy }">
                    <UiIcon name="arrows-shuffle" />{{ group.academy ? '学院绿窝配对' : '普通配对' }}
                  </span>
                  <span class="home-pair-basis">{{ group.inferred ? '小窝范围推断' : '场景观测' }}</span>
                </header>
                <div class="home-pair-parents">
                  <div class="home-parent">
                    <span class="home-parent-avatar is-mother">
                      <img v-if="residentFor(group.motherActorId)?.icon_url" :src="residentFor(group.motherActorId)?.icon_url" alt="">
                      <span v-else>♀</span>
                    </span>
                    <span class="home-parent-copy">
                      <strong>{{ group.motherName }}</strong>
                      <small>母本<template v-if="group.motherNature"> · {{ group.motherNature }}</template></small>
                    </span>
                  </div>
                  <UiIcon class="home-pair-join" name="chevron-right" />
                  <div
                    class="home-parents-list"
                    @pointerdown="startFatherDrag"
                    @pointermove="moveFatherDrag"
                    @pointerup="stopFatherDrag"
                    @pointercancel="stopFatherDrag"
                    @lostpointercapture="stopFatherDrag"
                  >
                    <span v-for="father in group.fathers" :key="father.actorId" class="home-parent">
                      <span class="home-parent-avatar is-father">
                        <img v-if="residentFor(father.actorId)?.icon_url" :src="residentFor(father.actorId)?.icon_url" alt="">
                        <span v-else>♂</span>
                      </span>
                      <span class="home-parent-copy">
                        <strong>{{ father.name }}</strong>
                        <small>父本<template v-if="father.nature"> · {{ father.nature }}</template></small>
                      </span>
                    </span>
                    <span v-if="!group.fathers.length" class="home-pair-missing">父本尚未识别</span>
                  </div>
                </div>
                <div class="home-pair-result">
                  <span class="home-pair-egg">
                    <img v-if="group.eggIcon" :src="group.eggIcon" alt="">
                    <UiIcon v-else name="egg" />
                    <strong>{{ group.eggName }}</strong>
                  </span>
                  <span class="home-pair-facts">蛋重 {{ group.eggWeight }} · 分贝 {{ group.voiceRange }}</span>
                </div>
                <div class="home-nature">
                  <div class="home-nature-cap"><span>性格概率</span><span>父本均等</span></div>
                  <div v-for="row in group.natures" :key="row.name" class="home-nature-row" :class="`is-${row.kind}`">
                    <span>{{ row.name }}</span>
                    <i><b :style="{ width: `${Math.max(0, Math.min(100, row.percent))}%` }" /></i>
                    <em>{{ row.percentText }}</em>
                  </div>
                </div>
              </article>
            </div>
            <div v-else-if="model.data.value.couples_stale" class="home-inline-empty">
              <UiIcon name="arrows-shuffle" />
              <strong>家园变化后配对关系尚未刷新</strong>
              <p>等待下一次完整场景快照即可恢复。</p>
            </div>
            <div v-else class="home-inline-empty">
              <UiIcon name="arrows-shuffle" />
              <strong>还没有配对记录</strong>
              <p>把母本与父本放进同一个小窝，场景快照更新后会显示配对关系。</p>
            </div>
          </section>
        </aside>
      </div>
    </template>
  </PageShell>
</template>
