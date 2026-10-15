<script setup lang="ts">
import type { PetFilterModel } from '../composables/usePetFilters'
import DualRangeSlider from './DualRangeSlider.vue'
import UiIcon from './UiIcon.vue'

const { model } = defineProps<{ model: PetFilterModel }>()
const { filters, options, fixed, selectedMedals } = model
function value(event: Event) { return (event.target as HTMLInputElement).value }
function setSortDirection(desc: boolean) { if (filters.desc !== desc) model.patch({ desc }) }
</script>

<template>
  <Teleport to="#pet-search-controls">
    <label class="pet-search"><span class="sr-only">搜索名字、编号或图鉴 ID</span>
      <input
        id="f-search" :value="filters.search" type="text" placeholder="搜索名字 / 编号 / 图鉴 ID"
        autocomplete="off" @input="model.search(value($event))">
    </label>
  </Teleport>
  <Teleport to="#pet-sort-root">
    <label class="inline-field pet-sort-field" :hidden="fixed">排序
      <select id="f-sort" v-model="filters.sort" :disabled="fixed" @change="model.changed()">
        <option v-for="item in options.sorts" :key="item.key" :value="item.key">{{ item.label }}</option>
      </select>
    </label>
    <div v-if="!fixed" class="segmented pet-sort-direction" role="group" aria-label="排序方向">
      <button type="button" :class="{ active: !filters.desc }" :aria-pressed="!filters.desc" @click="setSortDirection(false)"><UiIcon name="arrow-up"></UiIcon>升</button>
      <button type="button" :class="{ active: filters.desc }" :aria-pressed="filters.desc" @click="setSortDirection(true)"><UiIcon name="arrow-down"></UiIcon>倒</button>
    </div>
  </Teleport>
  <section class="direct-filter" style="order: 0">
<h3>异色与炫彩</h3><div class="filter-pair">
    <button v-for="key in (['shiny', 'colorful'] as const)" :key="key" class="chip" :class="{ active: filters[key] }" :aria-pressed="filters[key]" @click="filters[key] = !filters[key]; model.changed()">{{ key === 'shiny' ? '异色' : '炫彩' }}</button>
  </div>
</section>
  <section class="direct-filter" style="order: 1">
<h3>性别</h3><div id="f-gender" class="filter-pair">
    <button v-for="item in ([1, 2] as const)" :key="item" class="chip" :class="{ active: filters.gender === item }" :aria-pressed="filters.gender === item" @click="filters.gender = filters.gender === item ? 0 : item; model.changed()">{{ item === 1 ? '雄性' : '雌性' }}</button>
  </div>
</section>
  <details class="filter-section" style="order: 2">
<summary>奖牌<small>{{ selectedMedals.map(id => options.medals?.find(item => item.id === id)?.name || id).join('、') || '不限' }}</small></summary>
    <div class="chip-group medal-choices"><button v-for="item in options.medals" :key="item.id" class="chip" :class="{ active: selectedMedals.includes(item.id) }" :aria-pressed="selectedMedals.includes(item.id)" @click="model.medal(item.id)"><img v-if="item.id" :src="`/static/medal-icons/${item.id}.png`" alt="" @error="($event.target as HTMLImageElement).hidden = true"><span>{{ item.name }}</span></button></div>
    <button v-if="selectedMedals.length || filters.pool.includes('medal')" class="text-button filter-clear" @click="model.patch({ medal: 0, medals: [], marks: [], pool: filters.pool.filter(item => item !== 'medal') })">清除奖牌</button>
  </details>
  <details class="filter-section" style="order: 3">
<summary>等级<small id="f-level-label">{{ filters.level_min }} – {{ filters.level_max }}</small></summary>
    <DualRangeSlider field="level" label="等级" unit="级" :min="1" :max="60" :step="1" :low="filters.level_min" :high="filters.level_max" @input="(bound, value) => model.level(bound, value)"></DualRangeSlider>
  </details>
  <details class="filter-section" style="order: 4">
<summary>系别<small data-filter-summary="types" :title="filters.types.join('、')">{{ filters.types.join('、') || '不限' }}</small></summary>
    <div id="f-types" class="chip-group type-choices"><button v-for="name in options.types" :key="name" class="chip" :data-type="name" :class="{ active: filters.types.includes(name) }" :aria-pressed="filters.types.includes(name)" @click="model.type(name)"><img v-if="options.type_icons?.[name]" class="filter-type-icon" :src="options.type_icons[name]" alt=""><span>{{ name === '普通' ? '普' : name === '机械' ? '机' : name }}</span></button></div>
    <button v-if="filters.types.length" class="text-button filter-clear" @click="model.patch({ types: [] })">清除系别</button>
  </details>
  <details class="filter-section" style="order: 6">
<summary>性格<small data-filter-summary="natures">{{ filters.natures.map(id => options.natures.find(item => item.id === id)?.name || id).join('、') || '不限' }}</small></summary>
    <div id="f-natures" class="chip-group"><button v-for="item in options.natures" :key="item.id" class="chip" :data-nature="item.id" :class="{ active: filters.natures.includes(item.id) }" :aria-pressed="filters.natures.includes(item.id)" @click="model.nature(item.id)">{{ item.name }}</button></div>
    <button v-if="filters.natures.length" class="text-button filter-clear" @click="model.patch({ natures: [] })">清除性格</button>
    <p v-if="filters.natures.length > 1 && filters.pool_mode === 'and'" class="filter-note">AND 要求同时符合多个性格，会无匹配；可只选一种或改用 OR。</p>
  </details>
  <details class="filter-section" style="order: 7">
<summary>特性<small>{{ filters.speciality ? options.specialities?.find(item => item.id === filters.speciality)?.name : '不限' }}</small></summary>
    <div class="chip-group"><button v-for="item in options.specialities" :key="item.id" class="chip" :class="{ active: filters.speciality === item.id }" :aria-pressed="filters.speciality === item.id" @click="model.patch({ speciality: filters.speciality === item.id ? 0 : item.id })">{{ item.name }}</button></div>
    <p v-if="!options.specialities?.length" class="filter-note">当前背包没有已采集的特性。</p>
    <button v-if="filters.speciality" class="text-button filter-clear" @click="model.patch({ speciality: 0 })">清除特性</button>
  </details>
  <details class="filter-section" style="order: 8"><summary>获取方式<small>{{ filters.acquisition ? options.acquisitions?.find(item => item.id === filters.acquisition)?.name : '不限' }}</small></summary><div class="chip-group"><button v-for="item in options.acquisitions" :key="item.id" class="chip" :aria-pressed="filters.acquisition === item.id" :class="{ active: filters.acquisition === item.id }" @click="model.patch({ acquisition: filters.acquisition === item.id ? 0 : item.id })">{{ item.name }}</button></div></details>
  <details class="filter-section" style="order: 12">
    <summary>捕获日期<small>{{ filters.captured_days ? '近 ' + filters.captured_days + ' 天' : '不限' }}</small></summary>
    <div class="chip-group"><button v-for="[days, label] in ([[1, '一天内'], [3, '三天内'], [7, '一周内']] as const)" :key="days" class="chip" :class="{ active: filters.captured_days === days }" :aria-pressed="filters.captured_days === days" @click="model.patch({ captured_days: filters.captured_days === days ? 0 : days })">{{ label }}</button></div>
  </details>
</template>
