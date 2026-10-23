<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { useHome, type HomeHost } from '../composables/useHome'
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

function pairingModeLabel(group: HomeCouple[]) {
  return group.some(couple => couple.mode !== 'ordinary') ? '学院绿窝配对' : '普通配对'
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

function measurementPercent(ratio: number | null) {
  return ratio === null ? '—' : `${Math.round(Math.max(0, Math.min(1, ratio)) * 100)}%`
}

function resetAccount() {
  model.resetAccount()
}

defineExpose({ load: model.load, resume: model.resume, pause: model.pause, resetAccount })
</script>

<template>
  <div class="home-page" data-vue-page>
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
            <span class="home-sprite-count">{{ homeSprites.length }} 只</span>
          </div>
        </header>
        <div v-if="homeSprites.length" class="home-resident-grid">
          <article v-for="resident in homeSprites" :key="resident.actor_id" class="home-resident-card" :class="`gender-${resident.gender}`">
            <div class="home-resident-art">
              <div class="home-portrait">
                <img v-if="resident.icon_url && !failedImages.has(resident.actor_id)" class="home-resident-image" :src="resident.icon_url" alt="" loading="lazy" draggable="false" @error="failedImage(resident.actor_id)">
              </div>
            </div>
            <div class="home-resident-copy">
              <div class="home-resident-title">
                <strong>{{ resident.name }}</strong>
                <img v-if="rarityIconUrl(resident)" class="home-rarity-icon" :src="rarityIconUrl(resident)" :alt="resident.is_colorful ? '异色炫彩' : '异色'" :title="resident.is_colorful ? '异色炫彩' : '异色'" draggable="false">
                <span class="home-gender-symbol" :class="`gender-${resident.gender}`" :aria-label="genderLabel(resident.gender)" :title="genderLabel(resident.gender)">
                  <UiIcon v-if="resident.gender === 1 || resident.gender === 2" :name="resident.gender === 1 ? 'gender-male' : 'gender-female'" />
                  <span v-if="resident.gender !== 1 && resident.gender !== 2">{{ genderLabel(resident.gender) }}</span>
                </span>
              </div>
              <div v-if="resident.species_name && resident.species_name !== resident.name" class="home-resident-species">{{ resident.species_name }}</div>
              <div v-else-if="!resident.species_name" class="home-resident-species">物种资料未收录</div>
              <div v-if="resident.nature_name || portraitMedals(resident).length" class="home-resident-traits">
                <span v-if="resident.nature_name"><span>性格</span><strong>{{ resident.nature_name }}</strong></span>
                <img v-for="mark in portraitMedals(resident)" :key="mark.name" class="home-resident-medal-icon" :src="`/static/medal-icons/mark-${medalIds[mark.name]}.webp`" :alt="mark.name" :title="mark.name" draggable="false">
              </div>
              <div class="home-resident-measurements">
                <span :class="{ unknown: resident.height_pct === null }" :style="{ '--ratio': Math.max(0, Math.min(1, resident.height_pct ?? 0)) }">
                  <UiIcon name="ruler-2" /><span>身高</span><strong>{{ measurementPercent(resident.height_pct) }}</strong><i><b></b></i>
                </span>
                <span :class="{ unknown: resident.weight_pct === null }" :style="{ '--ratio': Math.max(0, Math.min(1, resident.weight_pct ?? 0)) }">
                  <UiIcon name="weight" /><span>体重</span><strong>{{ measurementPercent(resident.weight_pct) }}</strong><i><b></b></i>
                </span>
                <span :class="{ unknown: resident.voice === null }" :style="resident.voice === null ? undefined : { '--ratio': Math.max(0, Math.min(1, (resident.voice + 100) / 200)) }" :title="resident.voice === null ? '声音刻度 −100 至 100 dB' : `声音刻度 −100 至 100 dB；当前 ${resident.voice} dB`">
                  <UiIcon name="activity" /><span>声音</span><strong>{{ resident.voice === null ? '—' : measurementPercent((resident.voice + 100) / 200) }}</strong><i><b v-if="resident.voice !== null"></b></i>
                </span>
              </div>
            </div>
          </article>
        </div>
        <div v-else class="home-empty-inline">
          <strong>当前快照没有家园精灵记录</strong>
          <p>进入家园并等待场景快照更新后再查看。</p>
        </div>
      </section>

      <aside class="home-side">
        <section class="home-panel home-breeding-panel">
          <header class="home-panel-heading">
            <div><h2>家园配对关系</h2><span class="home-couple-count">{{ pairingGroups.length }} 个母本</span></div>
            <span v-if="model.data.value.couples_stale" class="home-pending-tag">关系待刷新</span>
          </header>
          <div v-if="pairingGroups.length" class="home-couple-list">
            <section v-for="(group, groupIndex) in pairingGroups" :key="groupIndex" class="home-couple-group" :class="{ 'home-couple-group--academy': group.some(couple => couple.mode !== 'ordinary') }">
              <div class="home-couple-heading">
                <strong>{{ pairingModeLabel(group) }}</strong>
              </div>
              <div class="home-pair-parents">
                <div class="home-pair-parent home-pair-mother">
                  <small>母本：</small>
                  <div class="home-pair-portrait">
                    <img v-if="residentFor(group[0].female_actor_id)?.icon_url" :src="residentFor(group[0].female_actor_id)?.icon_url" alt="">
                    <span v-else>♀</span>
                  </div>
                  <strong>{{ group[0].female_name }}</strong>
                </div>
                <div class="home-pair-fathers" @pointerdown="startFatherDrag" @pointermove="moveFatherDrag" @pointerup="stopFatherDrag" @pointercancel="stopFatherDrag" @lostpointercapture="stopFatherDrag">
                  <small>父本：</small>
                  <div class="home-pair-father-list">
                    <div v-for="father in fathersFor(group)" :key="father.actorId" class="home-pair-parent">
                      <div class="home-pair-portrait">
                        <img v-if="residentFor(father.actorId)?.icon_url" :src="residentFor(father.actorId)?.icon_url" alt="">
                        <span v-else>♂</span>
                      </div>
                      <strong>{{ father.name }}</strong>
                    </div>
                  </div>
                  <div v-if="!fathersFor(group).length" class="home-pair-missing">父本尚未识别</div>
                </div>
              </div>
              <div class="home-pair-egg">
                <div class="home-pair-egg-name">
                  <span>生蛋</span>
                  <img v-if="residentFor(group[0].female_actor_id)?.egg_icon_url" :src="residentFor(group[0].female_actor_id)?.egg_icon_url" alt="">
                  <strong>{{ residentFor(group[0].female_actor_id)?.egg_name || '蛋种待确认' }}</strong>
                </div>
                <div class="home-pair-estimates">
                  <span>蛋重 {{ eggWeightText(group[0].female_actor_id) }}</span>
                  <span>分贝 {{ voiceRangeText(group) }}</span>
                </div>
              </div>
              <div v-for="(couple, coupleIndex) in group" :key="`${couple.female_actor_id}:${coupleIndex}`" class="home-pair-nature">
                <div class="home-nature-list" aria-label="性格概率">
                  <div v-for="row in naturePredictionRows(couple)" :key="row.name" class="home-nature-item" :class="`nature-${row.name === '随机' ? 'random' : row.name === '待确认' ? 'unknown' : 'known'}`" :title="`${row.name} ${percentText(row.percent)}`">
                    <strong>{{ row.name }}</strong>
                    <span class="home-nature-track"><i :style="{ width: `${Math.max(0, Math.min(100, row.percent))}%` }"></i></span>
                    <span class="home-nature-percent">{{ percentText(row.percent) }}</span>
                  </div>
                </div>
              </div>
            </section>
          </div>
          <p v-else-if="model.data.value.couples_stale">家园变化后配对记录尚未刷新。</p>
          <p v-else>当前完整快照没有记录产蛋配对关系。</p>
        </section>

      </aside>
    </div>
  </div>
</template>
