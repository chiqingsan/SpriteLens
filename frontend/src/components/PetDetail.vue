<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Pet, PetBox } from '../types/pets'
import PetDetailHero from './PetDetailHero.vue'
import PetDetailStats from './PetDetailStats.vue'
import PetMeasurementRow from './PetMeasurementRow.vue'
import PetDetailEvolution from './PetDetailEvolution.vue'
import UiSegmented from './UiSegmented.vue'
const { pet, boxes } = defineProps<{ pet: Pet; boxes: PetBox[] }>()
const egg = ref(false)
const measurementFields = computed(() => egg.value ? ['height', 'weight'] as const : ['height', 'weight', 'voice'] as const)
const place = computed(() => pet.location)
const historical = computed(() => { const value = place.value; return value && ('team_id' in value ? value.historical : boxes.find(box => box.box_id === value.box_id)?.historical) })
const location = computed(() => !place.value ? '位置未采集' : 'team_id' in place.value ? '第 ' + place.value.team_id + ' 队 · 第 ' + place.value.slot + ' 格' : '第 ' + place.value.box_id + ' 箱 · 第 ' + place.value.row + ' 行第 ' + place.value.column + ' 列')
const acquired = computed(() => pet.add_time ? new Date(pet.add_time * 1000).toLocaleString('zh-CN', { hour12: false }) : '未采集')
</script>
<template>
  <PetDetailHero :pet="pet" />
  <div class="detail-stats-position">
    <PetDetailStats :pet="pet" />
    <section class="detail-position detail-block">
      <h3>{{ place && 'team_id' in place ? '出战背包位置' : '背包位置' }}</h3><p>{{ location }}</p>
      <div v-if="place" class="detail-position-matrix" :class="{ 'team-matrix': 'team_id' in place }" role="img" :aria-label="location">
        <div class="detail-position-columns" aria-hidden="true"><span v-for="column in 6" :key="column">{{ column }}</span></div>
        <div class="detail-position-rows" aria-hidden="true"><span v-for="row in ('team_id' in place ? 1 : 5)" :key="row">{{ row }}</span></div>
        <div class="pet-location-grid"><span v-for="slot in ('team_id' in place ? 6 : 30)" :key="slot" :class="{ active: slot === place.slot }"></span></div>
      </div>
      <p v-else class="filter-note">登录游戏后同步真实位置。</p>
      <div v-if="place && !historical" class="detail-position-footer"><small>最近采集的位置</small></div>
    </section>
  </div>
  <section class="detail-measurements">
    <header><h3>体型与声音</h3><UiSegmented aria-label="范围"><button :class="{ active: !egg }" :aria-pressed="!egg" @click="egg = false">精灵范围</button><button :class="{ active: egg }" :aria-pressed="egg" @click="egg = true">精灵蛋范围</button></UiSegmented></header>
    <PetMeasurementRow v-for="field in measurementFields" :key="field" :field="field" :measurement="pet.detail.measurements[field]" :reference-only="egg" :limits="egg && field !== 'voice' ? pet.detail.egg_limits[field] : pet.detail.measurements[field].limits" />
  </section>
  <PetDetailEvolution :pet="pet" />
  <footer class="detail-acquisition"><span>获取方式 <b>{{ pet.detail.acquisition_name }}</b></span><span>获得时间 <b>{{ acquired }}</b></span></footer>
</template>
