<script setup lang="ts">
import UiSelect from './UiSelect.vue'
import { computed, ref } from 'vue'
import type { WikiSkill } from '../types/wikiReference'
import UiSearch from './UiSearch.vue'
import UiSelect from './UiSelect.vue'
const { skills } = defineProps<{ skills: WikiSkill[] }>()
const search = ref(''), source = ref(''), type = ref('')
const types = computed(() => [...new Set(skills.map(row => row.type))])
const sourceOptions = [{ value: '', label: '全部来源' }, { value: '自学', label: '自学' }, { value: '技能石', label: '技能石' }, { value: '血脉', label: '血脉' }]
const typeOptions = computed(() => [{ value: '', label: '全部属性' }, ...types.value.map(name => ({ value: name, label: name }))])
const filtered = computed(() => skills.filter(row => (!source.value || row.source === source.value)
  && (!type.value || row.type === type.value) && (!search.value.trim()
    || `${row.name} ${row.description}`.includes(search.value.trim()))))
</script>
<template>
  <div class="wiki-skill-filters">
    <UiSearch v-model="search" label="搜索技能" placeholder="搜索技能名称 / 效果" />
    <UiSelect size="sm" :options="sourceOptions" :model-value="source" label="技能来源" @change="source = String($event ?? '')" />
    <UiSelect size="sm" :options="typeOptions" :model-value="type" label="技能属性" @change="type = String($event ?? '')" />
    <span class="count-badge">
      {{ filtered.length }} / {{ skills.length }} 条
    </span>
  </div>
  <div class="wiki-skills">
    <article v-for="(row, index) in filtered" :key="`${row.id}-${index}`" class="wiki-skill">
      <div class="wiki-skill-title">
        <strong>
          {{ row.name }}
        </strong>
        <span class="skill-chip">
          {{ row.type }}
        </span>
        <span class="muted">
          {{ row.category }}
        </span>
      </div>
      <div class="wiki-skill-values">
        <span>
          威力
          <b>
            {{ row.power ?? '—' }}
          </b>
        </span>
        <span>
          能耗
          <b>
            {{ row.energy ?? '—' }}
          </b>
        </span>
        <span>
          {{ row.source }}
          <template v-if="row.level !== null">
            · Lv.{{ row.level }}
          </template>
          <template v-if="row.blood">
            · {{ row.blood }}
          </template>
        </span>
      </div>
      <p>
        {{ row.description || '暂无效果描述' }}
      </p>
    </article>
    <p v-if="!filtered.length" class="muted">
      没有符合条件的技能。
    </p>
  </div>
</template>
