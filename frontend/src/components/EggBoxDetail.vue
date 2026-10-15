<script setup lang="ts">
import { computed, ref } from 'vue'
import type { EggBoxAnnotations, EggBoxEntry, EggBoxRange, EggNest, EggBoxVoiceTag } from '../types/eggBox'
import EggBoxArtwork from './EggBoxArtwork.vue'
import UiIcon from './UiIcon.vue'

const props = defineProps<{
  egg: EggBoxEntry
  position: number
  total: number
  favoriteSaving: boolean
  annotations: EggBoxAnnotations
  annotationError: string
  natureOptions: { id: number; name: string }[]
}>()
const emit = defineEmits<{
  previous: []
  next: []
  close: []
  favorite: [egg: EggBoxEntry]
  updateAnnotations: [value: EggBoxAnnotations]
  saveAnnotations: []
}>()
const closeButton = ref<HTMLButtonElement>()

function rangePercent(value: number, range: EggBoxRange | null) {
  if (value <= 0 || !range) return null
  return (value - range.min) / (range.max - range.min) * 100
}
function bounded(value: number) { return Math.max(0, Math.min(100, value)) }
function height(value: number) { return value > 0 ? `${Number((value / 100).toFixed(2))} m` : '暂无数据' }
function weight(value: number) { return value > 0 ? `${Number((value / 1000).toFixed(3))} kg` : '暂无数据' }
function percent(position: number | null) {
  if (position === null) return '范围未知'
  if (position < 0 || position > 100) return '超界'
  return `${position.toFixed(2)}%`
}
function weightReference(value: number) { return String(Number(value.toFixed(2))) }
function date(value: number) { return value > 0 ? new Date(value * 1000).toLocaleString() : '未知' }
const measurements = computed(() => [
  { id: 'height', label: '尺寸', value: height(props.egg.height_cm),
    position: rangePercent(props.egg.height_cm, props.egg.measurement_ranges.height_cm),
    range: props.egg.measurement_ranges.height_cm, format: height },
  { id: 'weight', label: '重量', value: weight(props.egg.weight_g),
    position: rangePercent(props.egg.weight_g, props.egg.measurement_ranges.weight_g),
    range: props.egg.measurement_ranges.weight_g, format: weight },
])
const hatchStatus = computed(() => {
  if (props.egg.hatching) return '正在孵化'
  return props.egg.hatch_known ? '尚未开始孵化' : '当前孵化状态未知'
})
const natureChoices = computed(() => {
  const options = [...props.natureOptions]
  if (props.annotations.nature_id && !options.some(option => option.id === props.annotations.nature_id)) {
    options.push({ id: props.annotations.nature_id, name: props.egg.tags.nature || `性格 #${props.annotations.nature_id}` })
  }
  return options
})
const nestChoices = [
  { value: 'normal', label: '普通窝' },
  { value: 'green', label: '学院绿窝' },
] as const
const voiceTagChoices = ['婉转声', '满分', '粗嗓门', '底分'] as const
const detailTags = computed(() => [
  ...(props.egg.tags.nature ? [props.egg.tags.nature] : []),
  ...(props.egg.tags.weight ? [props.egg.tags.weight] : []),
  ...props.egg.tags.medals,
  ...(props.egg.tags.nest ? [props.egg.tags.nest] : []),
  ...(props.egg.tags.voice ? [props.egg.tags.voice] : []),
])
const nestSelection = computed(() => props.annotations.nest_override || (props.egg.home_egg ? 'normal' : ''))
function savePatch(patch: Partial<EggBoxAnnotations>) {
  emit('updateAnnotations', { ...props.annotations, ...patch })
  emit('saveAnnotations')
}
function toggleNature(id: number) {
  savePatch({ nature_id: props.annotations.nature_id === id ? 0 : id })
}
function changeNest(selected: Exclude<EggNest, ''>) {
  savePatch({ nest_override: props.annotations.nest_override === selected ? '' : selected })
}
function changeVoiceTag(value: EggBoxVoiceTag) {
  savePatch({ voice_tag: props.annotations.voice_tag === value ? '' : value })
}
function updateNote(event: Event) {
  emit('updateAnnotations', { ...props.annotations, note: (event.currentTarget as HTMLTextAreaElement).value })
}

defineExpose({ focusClose: () => closeButton.value?.focus({ preventScroll: true }) })
</script>

<template>
  <header class="eggbox-detail-header">
    <div class="eggbox-detail-title"><h2>精灵蛋详情</h2><span>#{{ egg.instance_id }}</span></div>
    <div class="eggbox-detail-actions">
      <span class="sr-only">第 {{ position }} 枚，共 {{ total }} 枚</span>
      <button type="button" class="eggbox-favorite-button eggbox-detail-favorite" :class="{ active: egg.favorite }"
        :aria-label="egg.favorite ? '取消收藏' : '收藏这枚蛋'" :aria-pressed="egg.favorite" :disabled="favoriteSaving"
        @click="emit('favorite', egg)"><UiIcon :name="egg.favorite ? 'star-filled' : 'star'" /></button>
      <button type="button" class="ghost-button small" aria-label="上一枚" :disabled="total < 2" @click="emit('previous')"><UiIcon name="chevron-left" /></button>
      <button type="button" class="ghost-button small" aria-label="下一枚" :disabled="total < 2" @click="emit('next')"><UiIcon name="chevron-right" /></button>
      <button ref="closeButton" type="button" class="ghost-button small eggbox-mobile-close" @click="emit('close')"><UiIcon name="x" />关闭</button>
    </div>
  </header>

  <section class="eggbox-detail-hero">
    <EggBoxArtwork :egg="egg" size="hero" />
    <div class="eggbox-detail-identity">
      <h3>{{ egg.egg_name }}</h3>
      <p>{{ egg.species_name || (egg.special_egg_conf_id ? '孵化前物种未确定' : '对应物种未知') }}</p>
      <div class="eggbox-detail-tags">
        <span v-for="tag in detailTags" :key="tag" class="eggbox-tag eggbox-tag--medal">{{ tag }}</span>
      </div>
      <p v-if="annotations.note" class="eggbox-detail-note">{{ annotations.note }}</p>
    </div>
  </section>

  <aside v-if="egg.description" class="eggbox-detail-description">
    <p>{{ egg.description }}</p>
    <a v-if="egg.description_source" :href="egg.description_source" target="_blank" rel="noreferrer">来源：洛克王国世界 WIKI</a>
  </aside>

  <section class="eggbox-detail-section">
    <div class="eggbox-section-heading"><h3>数据对比</h3></div>
    <div class="eggbox-measurements">
      <article v-for="measurement in measurements" :key="measurement.id" class="eggbox-measurement" :class="`eggbox-measurement--${measurement.id}`">
        <div class="eggbox-measurement-heading">
          <span>{{ measurement.label }} <b>{{ measurement.value }}</b></span><strong>{{ percent(measurement.position) }}</strong>
        </div>
        <div class="eggbox-measurement-scale">
          <span>{{ measurement.range ? measurement.format(measurement.range.min) : '—' }}</span>
          <div class="eggbox-range-track" :class="{ 'is-unknown': measurement.position === null, 'is-outside': measurement.position !== null && (measurement.position < 0 || measurement.position > 100) }"
            role="img" :aria-label="`${measurement.label}${measurement.value}，范围位置${percent(measurement.position)}`"
          :title="measurement.range ? `${measurement.format(measurement.range.min)} — ${measurement.format(measurement.range.max)}` : '暂无目录范围'">
            <i v-if="measurement.position !== null" :style="{ width: `${bounded(measurement.position)}%` }"></i>
            <b v-if="measurement.position !== null" :style="{ left: `${bounded(measurement.position)}%` }"></b>
          </div>
          <span>{{ measurement.range ? measurement.format(measurement.range.max) : '—' }}</span>
        </div>
        <small v-if="measurement.id === 'weight' && measurement.range">
          体型参考：小不点 ≤{{ weightReference((measurement.range.min + (measurement.range.max - measurement.range.min) * .02) / 1000) }}kg · 大块头 ≥{{ weightReference((measurement.range.max - (measurement.range.max - measurement.range.min) * .02) / 1000) }}kg
        </small>
        <small v-else-if="!measurement.range" class="filter-note">暂无范围资料</small>
        <small v-if="measurement.position !== null && (measurement.position < 0 || measurement.position > 100)" class="eggbox-outside-note">实测值超出目录范围</small>
      </article>
    </div>
  </section>

  <section class="eggbox-edit-section" aria-labelledby="eggbox-traits-heading">
    <div class="eggbox-section-heading"><h3 id="eggbox-traits-heading">性格标签</h3></div>
    <div class="eggbox-nature-grid" role="group" aria-label="选择性格">
      <button v-for="option in natureChoices" :key="option.id" type="button" class="eggbox-nature-option"
        :class="{ selected: annotations.nature_id === option.id }" :aria-pressed="annotations.nature_id === option.id"
        @click="toggleNature(option.id)">
        {{ option.name }}
      </button>
    </div>
  </section>

  <section class="eggbox-edit-section" aria-labelledby="eggbox-nest-heading">
    <div class="eggbox-section-heading"><h3 id="eggbox-nest-heading">小窝类型</h3></div>
    <div class="eggbox-choice-grid" role="group" aria-label="选择小窝类型">
      <button v-for="option in nestChoices" :key="option.value" type="button" class="eggbox-choice-option"
        :class="{ selected: nestSelection === option.value }" :aria-pressed="nestSelection === option.value"
        @click="changeNest(option.value)">{{ option.label }}</button>
    </div>
  </section>

  <section class="eggbox-edit-section" aria-labelledby="eggbox-voice-heading">
    <div class="eggbox-section-heading"><h3 id="eggbox-voice-heading">声音标签</h3></div>
    <div class="eggbox-choice-grid" role="group" aria-label="选择声音标签">
      <button v-for="tag in voiceTagChoices" :key="tag" type="button"
        class="eggbox-choice-option" :class="{ selected: annotations.voice_tag === tag }" :aria-pressed="annotations.voice_tag === tag"
        @click="changeVoiceTag(tag)">{{ tag }}</button>
    </div>
  </section>

  <section class="eggbox-edit-section" aria-labelledby="eggbox-note-heading">
    <div class="eggbox-section-heading"><h3 id="eggbox-note-heading">备注</h3></div>
    <textarea :value="annotations.note" class="eggbox-note-input" maxlength="500" rows="3"
      placeholder="添加备注信息…" @input="updateNote" @blur="emit('saveAnnotations')"></textarea>
    <small v-if="annotationError" class="form-error" role="alert">{{ annotationError }}
      <button type="button" class="text-button" @click="emit('saveAnnotations')">重试保存</button>
    </small>
  </section>

  <section class="eggbox-detail-section eggbox-hatch-section">
    <div class="eggbox-section-heading"><h3>其他信息</h3></div>
    <div class="eggbox-hatch-content">
      <p class="eggbox-hatch-status" :class="{ active: egg.hatching }">{{ hatchStatus }}<template v-if="egg.hatching"> · {{ Math.round(egg.hatch_progress * 100) }}%</template></p>
      <div v-if="egg.hatching" class="eggbox-hatch-track"><i :style="{ width: `${Math.round(egg.hatch_progress * 100)}%` }"></i></div>
      <dl class="eggbox-detail-meta">
        <div><dt>获得时间</dt><dd>{{ date(egg.obtained_at) }}</dd></div>
        <div><dt>数量</dt><dd>{{ egg.quantity || 1 }} 枚</dd></div>
        <div><dt>记录来源</dt><dd>{{ egg.historical ? '历史缓存' : '已观察' }}</dd></div>
      </dl>
    </div>
  </section>
</template>
