<script setup lang="ts">
import { computed, onBeforeUnmount } from 'vue'
import { useBreederLibrary, type BreederHost } from '../composables/useBreederLibrary'
import BreederCard from '../components/BreederCard.vue'
import DualRangeSlider from '../components/DualRangeSlider.vue'
import UiIcon from '../components/UiIcon.vue'
import './breeder-library.css'

const props = defineProps<{ host: BreederHost }>()
const model = useBreederLibrary(props.host), { data, filters, loading, error, invalidRange } = model
const columns = computed(() => [
  { gender: 1, title: '父本', icon: 'gender-male', rows: data.value?.males || [], total: data.value?.male_total || 0, page: data.value?.male_page || 1, selected: model.male.value },
  { gender: 2, title: '母本', icon: 'gender-female', rows: data.value?.females || [], total: data.value?.female_total || 0, page: data.value?.female_page || 1, selected: model.female.value },
])
function toggle(key: 'groups' | 'natures' | 'marks', value: string) {
  filters[key] = filters[key].includes(value) ? filters[key].filter(item => item !== value) : [...filters[key], value]
}
function rangeSummary(field: 'voice' | 'height' | 'weight') {
  if (filters[`${field}_min`] === null && filters[`${field}_max`] === null) return '不限'
  const low = filters[`${field}_min`] ?? (field === 'voice' ? -100 : 0), high = filters[`${field}_max`] ?? 100
  const unit = field === 'voice' ? ' dB' : '%'
  return low === high ? `${low}${unit}` : `${low}～${high}${unit}`
}
function pause() { model.pause() }
function resetAccount() { model.resetAccount() }
onBeforeUnmount(pause)
defineExpose({ load: model.load, pause, resetAccount })
</script>

<template>
  <div class="breeder-page" data-vue-page>
    <section class="breeder-workspace panel">
      <header class="breeder-toolbar">
        <label class="breeder-search"><UiIcon name="search" /><input v-model="filters.search" type="search" aria-label="搜索配种精灵" placeholder="名称、性格、蛋组或个体 ID"></label>
        <label class="breeder-nature-toggle"><input v-model="filters.same_nature" type="checkbox">性格一致</label>
        <button class="ghost-button" title="刷新背包观察记录" aria-label="刷新筛选配对" @click="model.refresh"><UiIcon name="refresh" /></button>
      </header>
      <div class="breeder-status" :class="{ 'has-error': error || invalidRange }" role="status">
        <template v-if="invalidRange">请填写有效范围：声音 −100～100 dB，体型 0～100%，最小值不大于最大值。</template>
        <template v-else-if="error">{{ error }}<button class="breeder-detail-link" @click="model.refresh">重试</button></template>
        <template v-else-if="data && !data.available">静态目录不可用，暂时无法确认蛋组与配对条件。</template>
        <template v-else>{{ data?.source === 'history' ? '历史观察记录' : '当前账号观察记录' }} · {{ data?.pet_count ?? '—' }} 只<span>仅限同账号候选</span></template>
      </div>
      <div v-if="data?.selection_changed" class="breeder-notice" role="status">部分亲本已失效或不再兼容，已取消该项选择。</div>
      <div class="breeder-columns" :aria-busy="loading">
        <section v-for="column in columns" :key="column.gender" class="breeder-column" :class="`gender-${column.gender}`">
          <header><div class="breeder-column-title"><UiIcon :name="column.icon" /><h2>{{ column.title }}</h2><span class="count-badge">{{ column.total }}</span></div><div class="breeder-column-actions"><small>{{ data?.anchor ? data.anchor === column.gender ? '同进化链备选' : '可配候选' : `点击选择${column.title}` }}</small><div class="breeder-pagination"><button class="ghost-button" :disabled="column.page <= 1" :aria-label="`${column.title}上一页`" @click="model.paginate(column.gender, column.page - 1)"><UiIcon name="chevron-left" /></button><span>{{ column.page }} / {{ Math.max(1, Math.ceil(column.total / (data?.page_size || 24))) }}</span><button class="ghost-button" :disabled="column.page * (data?.page_size || 24) >= column.total" :aria-label="`${column.title}下一页`" @click="model.paginate(column.gender, column.page + 1)"><UiIcon name="chevron-right" /></button></div></div></header>
          <div class="breeder-grid">
            <BreederCard v-for="parent in column.rows" :key="parent.gid" :parent="parent" :selected="column.selected === parent.gid" @select="model.select" @open="host.openPet" />
            <div v-if="!column.rows.length" class="breeder-empty"><UiIcon :name="column.icon" /><strong>{{ loading && !data ? '正在读取背包…' : `暂无符合条件的${column.title}` }}</strong><p>{{ data?.pet_count ? '可调整筛选，或点击已选亲本取消选择。' : '开始采集并在游戏中浏览背包后，候选会自动显示。' }}</p></div>
          </div>
        </section>
      </div>
    </section>
    <aside class="breeder-inspector panel">
      <header class="breeder-inspector-tabs"><button class="active" aria-pressed="true"><UiIcon name="adjustments" />筛选设置</button></header>
      <div class="breeder-filter-content">
        <div class="breeder-section-heading"><strong>同时筛选父本与母本</strong><button class="breeder-detail-link" @click="model.resetFilters">重置筛选</button></div>
        <section><h3>奖牌标记 <small>多项同时满足</small></h3><div class="breeder-chips"><button v-for="mark in ['双奖牌', '大块头', '小不点', '婉转声', '粗嗓门']" :key="mark" class="chip" :class="{ active: filters.marks.includes(mark) }" :aria-pressed="filters.marks.includes(mark)" @click="toggle('marks', mark)">{{ mark }}</button></div></section>
        <section><h3>性格 <small>同类任选其一</small></h3><div class="breeder-chips"><button v-for="nature in data?.natures || []" :key="nature" class="chip" :class="{ active: filters.natures.includes(nature) }" :aria-pressed="filters.natures.includes(nature)" @click="toggle('natures', nature)">{{ nature }}</button></div></section>
        <section><h3>蛋组 <small>同类任选其一</small></h3><div class="breeder-chips"><button v-for="group in data?.groups || []" :key="group" class="chip" :class="{ active: filters.groups.includes(group) }" :aria-pressed="filters.groups.includes(group)" @click="toggle('groups', group)">{{ group }}</button><small v-if="!data?.groups.length">尚无可配种蛋组</small></div></section>
        <section class="breeder-ranges">
          <h3>数值范围</h3>
          <div v-for="field in (['voice', 'height', 'weight'] as const)" :key="field" class="breeder-range">
            <div class="breeder-range-heading"><span>{{ { voice: '声音', height: '身高', weight: '体重' }[field] }}</span><b :class="{ active: filters[`${field}_min`] !== null || filters[`${field}_max`] !== null }">{{ rangeSummary(field) }}</b></div>
            <DualRangeSlider :field="`breeder-${field}`" :label="{ voice: '声音', height: '身高', weight: '体重' }[field]" :unit="field === 'voice' ? 'dB' : '%'" :min="field === 'voice' ? -100 : 0" :max="100" :step="field === 'voice' ? 1 : 0.1" :low="filters[`${field}_min`]" :high="filters[`${field}_max`]" @input="(bound, value, commit) => model.range(field, bound, value, commit)" />
          </div>
        </section>
      </div>
    </aside>
  </div>
</template>
