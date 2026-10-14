<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { defaultPetShortcuts, type PetShortcut } from '../types/petConditions'
import type { PetFilterOptions } from '../types/petFilters'
import UiIcon from './UiIcon.vue'
const props = defineProps<{ items: PetShortcut[]; options: PetFilterOptions; groups: string[]; saving: boolean; error: string }>()
const emit = defineEmits<{ save: [items: PetShortcut[]]; close: [] }>()
const dialog = ref<HTMLDialogElement>()
const draft = ref(props.items.slice())
const key = (item: PetShortcut) => JSON.stringify(item.filters)
const catalog = computed(() => {
  const named = (title: string, field: 'medal' | 'speciality' | 'acquisition', values: { id: number; name: string }[] = []) => ({ title,
    items: values.map(item => ({ name: item.name, filters: field === 'medal' ? defaultPetShortcuts.find(value => value.name === item.name)?.filters || { medals: [item.id] } : { [field]: item.id } })) })
  const groups: { title: string; items: PetShortcut[] }[] = [
    named('奖牌', 'medal', props.options.medals),
    { title: '异色与炫彩', items: [{ name: '异色', filters: { shiny: true } }, { name: '炫彩', filters: { colorful: true } }] },
    { title: '性别', items: [{ name: '雄性', filters: { gender: 1 } }, { name: '雌性', filters: { gender: 2 } }] },
    { title: '系别', items: props.options.types.map(name => ({ name, filters: { types: [name] } })) },
    { title: '蛋组', items: props.groups.map(name => ({ name, filters: { egg_groups: [name] } })) },
    { title: '性格', items: props.options.natures.map(item => ({ name: item.name, filters: { natures: [item.id] } })) },
    named('特性', 'speciality', props.options.specialities), named('获取方式', 'acquisition', props.options.acquisitions),
    { title: '捕获日期', items: [1, 3, 7].map(days => ({ name: `近${days}天`, filters: { captured_days: days } })) },
  ]
  const keys = new Set(groups.flatMap(group => group.items.map(key)))
  const others = props.items.filter(item => !keys.has(key(item)))
  if (others.length) groups.push({ title: '已保存的组合与范围', items: others })
  return groups
})
function toggle(item: PetShortcut) {
  const id = key(item)
  draft.value = draft.value.some(value => key(value) === id) ? draft.value.filter(value => key(value) !== id) : [...draft.value, item]
}
onMounted(() => dialog.value!.showModal())
</script>
<template>
  <Teleport to="body">
    <dialog id="quick-settings-dialog" ref="dialog" class="quick-settings-dialog" aria-labelledby="quick-settings-title" @cancel.prevent="!saving && emit('close')">
      <header><h2 id="quick-settings-title">快捷条件设置</h2><button type="button" class="icon-button" aria-label="关闭快捷条件设置" :disabled="saving" @click="emit('close')"><UiIcon name="x"></UiIcon></button></header>
      <p class="filter-note">勾选具体选项，保存后固定到快捷条件；点击快捷项与详细条件同步生效。</p>
      <div class="quick-settings-scroll">
        <section v-for="group in catalog" :key="group.title">
          <h3>{{ group.title }}</h3><div class="quick-setting-list">
          <label v-for="item in group.items" :key="key(item)"><input type="checkbox" :checked="draft.some(value => key(value) === key(item))" :disabled="saving" @change="toggle(item)"><span>{{ item.name }}</span></label>
          </div>
        </section>
        <p v-if="error" role="alert" class="filter-note">保存失败：{{ error }}；可重试。</p>
      </div>
      <footer><button type="button" class="primary-button" :disabled="saving" @click="emit('save', draft)">{{ saving ? '保存中…' : '保存设置' }}</button></footer>
    </dialog>
  </Teleport>
</template>
