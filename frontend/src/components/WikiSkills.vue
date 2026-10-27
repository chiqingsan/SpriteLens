<script setup lang="ts">
import UiSelect from './UiSelect.vue'
import { computed, ref } from 'vue'
import type { WikiSkill } from '../types/wikiReference'
const { skills } = defineProps<{ skills: WikiSkill[] }>()
const search = ref(''), source = ref(''), type = ref('')
const types = computed(() => [...new Set(skills.map(row => row.type))])
const filtered = computed(() => skills.filter(row => (!source.value || row.source === source.value)
  && (!type.value || row.type === type.value) && (!search.value.trim()
    || `${row.name} ${row.description}`.includes(search.value.trim()))))
</script>
<template>
  <div class="wiki-skill-filters">
    <input v-model="search" type="search" placeholder="搜索技能名称 / 效果" aria-label="搜索技能">
    <UiSelect v-model="source" label="技能来源" :options="[{ value: '', label: '全部来源' }, ...['自学', '技能石', '血脉'].map(name => ({ value: name, label: name }))]" />
    <UiSelect v-model="type" label="技能属性" :options="[{ value: '', label: '全部属性' }, ...types.map(name => ({ value: name, label: name }))]" />
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
