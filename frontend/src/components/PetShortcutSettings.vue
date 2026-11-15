<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { defaultPetShortcuts, type PetConditions, type PetShortcut } from '../types/petConditions'
import type { PetFilterOptions } from '../types/petFilters'
import MedalIcon from './MedalIcon.vue'
import UiIcon from './UiIcon.vue'
import UiSearch from './UiSearch.vue'
const props = defineProps<{ items: PetShortcut[]; options: PetFilterOptions; groups: string[]; saving: boolean; error: string }>()
const emit = defineEmits<{ save: [items: PetShortcut[]]; close: [] }>()
const dialog = ref<HTMLDialogElement>()
const draft = ref(props.items.slice())
const query = ref('')
const key = (item: PetShortcut) => JSON.stringify(item.filters)
// 每个条件对应的图标：奖牌用真实奖牌图，异色/炫彩用稀有度图标，其余用语义化 UiIcon。
interface Entry { name: string; filters: Partial<PetConditions>; icon?: string; medalId?: number; image?: string }
interface Group { title: string; icon: string; entries: Entry[] }
// 异色/炫彩沿用背包卡片与附近页的同款本地图标。
const rarityIcons = { shiny: '/static/rarity/shiny-fit.webp', colorful: '/static/rarity/colorful-fit.webp' }
const catalog = computed<Group[]>(() => {
  const named = (title: string, icon: string, field: 'speciality' | 'acquisition', values: { id: number; name: string }[] = []) => ({
    title, icon, entries: values.map(item => ({ name: item.name, filters: { [field]: item.id } })) })
  const groups: Group[] = [
    {
      title: '奖牌', icon: 'flag',
      entries: (props.options.medals || []).map(item => {
        const preset = defaultPetShortcuts.find(value => value.name === item.name)
        // 目录里只有本地有图的十个基础奖牌，直接按奖牌 id 画真实奖牌图；
        // 快捷项保存的仍是名称与筛选条件，图标不进入偏好。
        return { name: item.name, filters: preset?.filters || { medals: [item.id] }, medalId: item.id }
      }),
    },
    {
      title: '异色与炫彩', icon: 'star',
      entries: [{ name: '异色', filters: { shiny: true }, image: rarityIcons.shiny }, { name: '炫彩', filters: { colorful: true }, image: rarityIcons.colorful }],
    },
    {
      title: '性别', icon: 'users',
      entries: [{ name: '雄性', filters: { gender: 1 }, icon: 'gender-male' }, { name: '雌性', filters: { gender: 2 }, icon: 'gender-female' }],
    },
    {
      title: '系别', icon: 'layout-grid',
      entries: props.options.types.map(name => ({ name, filters: { types: [name] } })),
    },
    // 同一组里每个选项图标都一样时不画图标：重复图形只是噪点，扫视靠分组标题就够。
    { title: '蛋组', icon: 'egg', entries: props.groups.map(name => ({ name, filters: { egg_groups: [name] } })) },
    { title: '性格', icon: 'activity', entries: props.options.natures.map(item => ({ name: item.name, filters: { natures: [item.id] } })) },
    named('特性', 'sprout', 'speciality', props.options.specialities),
    named('获取方式', 'box', 'acquisition', props.options.acquisitions),
    { title: '捕获日期', icon: 'clock', entries: [1, 3, 7].map(days => ({ name: `近${days}天`, filters: { captured_days: days }, icon: 'clock' })) },
  ]
  const known = new Set(groups.flatMap(group => group.entries.map(key)))
  const others = props.items.filter(item => !known.has(key(item)))
  if (others.length) groups.push({ title: '已保存的组合与范围', icon: 'checklist', entries: others.map(item => ({ name: item.name, filters: item.filters, icon: 'star-filled' })) })
  return groups
})
// 搜索只过滤显示的分组，不清空已勾选项；分组内没有命中时整组隐藏。
const visibleGroups = computed(() => {
  const text = query.value.trim().toLowerCase()
  if (!text) return catalog.value
  return catalog.value
    .map(group => ({ ...group, entries: group.entries.filter(entry => entry.name.toLowerCase().includes(text)) }))
    .filter(group => group.entries.length)
})
const selectedCount = computed(() => draft.value.length)
const previewNames = computed(() => draft.value.map(item => item.name).slice(0, 6))
function isPicked(item: PetShortcut) {
  return draft.value.some(value => key(value) === key(item))
}
function typeIcon(name: string) {
  return props.options.type_icons?.[name] || ''
}
function toggle(item: PetShortcut) {
  const id = key(item)
  // 只提交名称与筛选条件：图标是弹窗内的展示信息，不能写进持久化偏好。
  const entry: PetShortcut = { name: item.name, filters: item.filters }
  draft.value = draft.value.some(value => key(value) === id) ? draft.value.filter(value => key(value) !== id) : [...draft.value, entry]
}
function clearAll() {
  draft.value = []
}
function restoreDefaults() {
  draft.value = defaultPetShortcuts.slice()
}
onMounted(() => dialog.value!.showModal())
</script>
<template>
  <Teleport to="body">
    <dialog id="quick-settings-dialog" ref="dialog" class="quick-settings-dialog" aria-labelledby="quick-settings-title" @cancel.prevent="!saving && emit('close')">
      <header class="quick-settings-head">
        <div class="quick-settings-title">
          <span class="quick-settings-mark"><UiIcon name="filter" /></span>
          <div>
            <h2 id="quick-settings-title">快捷条件设置</h2>
            <p class="filter-note">勾选后固定到左侧「快捷条件」，点击快捷项即与详细条件同步生效。</p>
          </div>
        </div>
        <button type="button" class="icon-button" aria-label="关闭快捷条件设置" :disabled="saving" @click="emit('close')"><UiIcon name="x"></UiIcon></button>
      </header>

      <div class="quick-settings-toolbar">
        <UiSearch v-model="query" class="quick-settings-search" label="搜索条件" placeholder="搜索奖牌、系别、性格…" />
        <span class="quick-settings-count" aria-live="polite">已选 <strong>{{ selectedCount }}</strong> 项</span>
        <div class="quick-settings-tools">
          <button type="button" class="ghost-button small" :disabled="saving || !selectedCount" @click="clearAll"><UiIcon name="trash" />清空</button>
          <button type="button" class="ghost-button small" :disabled="saving" @click="restoreDefaults"><UiIcon name="refresh" />恢复默认 4 项</button>
        </div>
      </div>

      <div class="quick-settings-scroll">
        <section v-for="group in visibleGroups" :key="group.title" class="quick-settings-group">
          <h3 class="quick-settings-group-title"><UiIcon :name="group.icon" />{{ group.title }}<small>{{ group.entries.length }}</small></h3>
          <div class="quick-setting-list">
            <label v-for="item in group.entries" :key="key(item)" class="quick-setting-item" :class="{ 'is-picked': isPicked(item) }">
              <input type="checkbox" :checked="isPicked(item)" :disabled="saving" @change="toggle(item)">
              <span class="quick-setting-check" aria-hidden="true"><UiIcon name="circle-check" /></span>
              <span v-if="item.medalId || item.image || typeIcon(item.name) || item.icon" class="quick-setting-icon" aria-hidden="true">
                <MedalIcon v-if="item.medalId" :name="item.name" :medal-id="item.medalId" />
                <img v-else-if="item.image" :src="item.image" alt="">
                <img v-else-if="typeIcon(item.name)" :src="typeIcon(item.name)" alt="">
                <UiIcon v-else-if="item.icon" :name="item.icon" />
              </span>
              <span class="quick-setting-name">{{ item.name }}</span>
            </label>
          </div>
        </section>
        <p v-if="!visibleGroups.length" class="quick-settings-none">没有匹配的条件，换个关键词试试。</p>
        <p v-if="error" role="alert" class="filter-note quick-settings-error">保存失败：{{ error }}；可重试。</p>
      </div>

      <footer class="quick-settings-foot">
        <p class="quick-settings-preview">
          <template v-if="selectedCount">保存后显示：{{ previewNames.join('、') }}<template v-if="selectedCount > previewNames.length"> 等 {{ selectedCount }} 项</template></template>
          <template v-else>当前没有勾选任何条件，保存后快捷区会隐藏。</template>
        </p>
        <div class="quick-settings-foot-actions">
          <button type="button" class="ghost-button" :disabled="saving" @click="emit('close')">取消</button>
          <button type="button" class="primary-button" :disabled="saving" @click="emit('save', draft)">{{ saving ? '保存中…' : '保存设置' }}</button>
        </div>
      </footer>
    </dialog>
  </Teleport>
</template>
