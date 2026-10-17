<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import BreederCard from '../components/BreederCard.vue'
import BreedingCanvas from '../components/BreedingCanvas.vue'
import MedalIcon from '../components/MedalIcon.vue'
import UiIcon from '../components/UiIcon.vue'
import { useBreedingPlanner, type PlannerHost } from '../composables/useBreedingPlanner'
import type { Goal, Placement } from '../types/breedingPlanner'
import './breeder-library.css'
import './breeding-planner.css'

const props = defineProps<{ host: PlannerHost }>()
const model = useBreedingPlanner(props.host)
const { context, mode, draft, plan, result, busy, error, errorAction, notice, parents, dirty, unsaved } = model
const selected = ref(''), picker = ref<HTMLDialogElement | null>(null), pickerSearch = ref<HTMLInputElement | null>(null), pickerKind = ref<'pool' | 'replace' | 'add'>('pool')
const search = ref(''), gender = ref(''), nature = ref(''), group = ref(''), medal = ref(''), page = ref(1), eggSearch = ref('')
const iterationPage = ref(1), unusedPage = ref(1)
const selectedPage = ref(1)
const outcomes = ref<HTMLElement | null>(null)
const generationHint = computed(() => {
  if (busy.value) return { loading: '正在读取资料…', evaluate: '正在重评布局…', saving: '正在保存…', solve: '正在规划，请稍候…' }[busy.value]
  if (!context.value?.uid || !context.value.available) return '请先采集当前账号的背包资料'
  return ''
})
const saveHint = computed(() => {
  if (!context.value?.uid) return '请先采集当前账号的背包资料'
  if (busy.value === 'saving') return '正在保存当前入口草稿…'
  return unsaved.value ? '有未保存的修改' : ''
})
const placedIds = computed(() => new Set(draft.value.placements.map(p => p.gid)))
const selectedInPlan = computed(() => draft.value.selected.filter(gid => placedIds.value.has(gid)).length)
const placementCounts = computed(() => draft.value.placements.reduce((counts, position) => {
  const gender = parents.value.get(position.gid)?.gender
  if (gender === 1) counts.males++
  else if (gender === 2) counts.females++
  return counts
}, { males: 0, females: 0 }))
const goalSummary = (goal: Goal) => [goal.size_mark, goal.voice_mark, context.value?.natures.find(n => n.id === goal.nature_id)?.name, goal.priority ? '优先' : ''].filter(Boolean).join(' · ') || '奖牌、性格不限'
watch(mode, () => { selected.value = '' })
function changeGoal(goal: Goal, eggKey: string) {
  goal.egg_key = eggKey
  draft.value.approved = draft.value.approved.filter(key => !key.startsWith(`${goal.goal_id}:`))
  notice.value = '目标蛋已更换，奖牌、性格和优先级保留；原迭代选择已清除，请重新规划。'
}
const selectedPages = computed(() => Math.max(1, Math.ceil(draft.value.selected.length / 24)))
const currentSelectedPage = computed(() => Math.min(selectedPage.value, selectedPages.value))
const selectedRows = computed(() => draft.value.selected.slice((currentSelectedPage.value - 1) * 24, currentSelectedPage.value * 24))
const relevantIterations = computed(() => result.value?.iterations.filter(item => !item.has_exact || draft.value.approved.includes(item.key)) || [])
const iterationPages = computed(() => Math.max(1, Math.ceil(relevantIterations.value.length / 6)))
const currentIterationPage = computed(() => Math.min(iterationPage.value, iterationPages.value))
const iterationRows = computed(() => relevantIterations.value.slice((currentIterationPage.value - 1) * 6, currentIterationPage.value * 6))
const unusedPages = computed(() => Math.max(1, Math.ceil((plan.value?.unused_candidates.length || 0) / 24)))
const currentUnusedPage = computed(() => Math.min(unusedPage.value, unusedPages.value))
const unusedRows = computed(() => plan.value?.unused_candidates.slice((currentUnusedPage.value - 1) * 24, currentUnusedPage.value * 24) || [])
const selectedParent = computed(() => parents.value.get(selected.value))
const selectedPosition = computed(() => draft.value.placements.find(p => p.gid === selected.value))
const eggName = (key: string | null) => context.value?.eggs.find(e => e.egg_key === key)?.name || '蛋种资料待补'
const parentName = (gid: string) => parents.value.get(gid)?.name || `个体 ${gid}`
const markOutcomes = (gid: string) => Array.from(new Map((plan.value?.edges.filter(e => e.female === gid) || []).map(edge => [edge.marks.join('＋'), edge.marks] as [string, string[]])).values())
const percent = (value: number | null | undefined) => value === null || value === undefined ? '未知' : `${Math.round(value * 100)}%`
const statusName: Record<string, string> = { ready: '规划参考就绪', partial: '部分支持', no_plan: '暂未形成有效配对', invalid: '存在布局冲突' }
const kindName: Record<string, string> = { exact: '合格组合', iterative: '迭代参考', unknown: '资料待补' }
const currentGroups = computed(() => [...new Set(context.value?.parents.flatMap(p => p.groups) || [])].sort())
const filtered = computed(() => context.value?.parents.filter(p => {
  if (pickerKind.value === 'replace' && draft.value.placements.some(pos => pos.gid === p.gid)) return false
  if (pickerKind.value === 'add' && draft.value.placements.some(pos => pos.gid === p.gid)) return false
  return (!gender.value || String(p.gender) === gender.value) && (!nature.value || p.nature === nature.value)
    && (!group.value || p.groups.includes(group.value)) && (!medal.value || p.marks.some(m => m.name === medal.value))
    && (!search.value.trim() || [p.name, p.species, p.gid, p.nature, ...p.groups].join(' ').toLowerCase().includes(search.value.trim().toLowerCase()))
}) || [])
const pickerRows = computed(() => filtered.value.slice((page.value - 1) * 24, page.value * 24))
const eggChoices = computed(() => context.value?.eggs.filter(e => !eggSearch.value.trim() || `${e.name} ${e.groups.join(' ')} ${(e.chain_names || []).join(' ')}`.toLowerCase().includes(eggSearch.value.trim().toLowerCase())) || [])
const motherCounts = computed(() => {
  const counts = new Map<string, number>()
  context.value?.parents.filter(p => p.gender === 2 && p.egg_key).forEach(p => counts.set(p.egg_key!, (counts.get(p.egg_key!) || 0) + 1))
  return counts
})
const visibleEggChoices = computed(() => [...eggChoices.value].sort((a, b) => (motherCounts.value.get(b.egg_key) || 0) - (motherCounts.value.get(a.egg_key) || 0)).slice(0, 24))
// 上下文、结果与方案的问题合并成一份去重列表，避免同一原因重复渲染。
const issues = computed(() => [...new Set([...(context.value?.issues || []), ...(result.value?.issues || []), ...(plan.value?.issues || [])])])
let goalSequence = 0
function addGoal(eggKey: string) {
  const egg = context.value?.eggs.find(e => e.egg_key === eggKey)
  if (!egg) return
  if (draft.value.goals.some(goal => goal.egg_key === egg.egg_key && !goal.size_mark && !goal.voice_mark && !goal.nature_id && !goal.priority)) {
    notice.value = `${egg.name} 已在目标列表中，可直接编辑已有目标的奖牌与性格。`
    return
  }
  draft.value.goals.push({ goal_id: `goal-${Date.now().toString(36)}-${++goalSequence}`, egg_key: egg.egg_key, size_mark: '', voice_mark: '', nature_id: 0, priority: 0 })
}
function removeGoal(id: string) {
  draft.value.goals = draft.value.goals.filter(g => g.goal_id !== id)
  draft.value.placements.forEach(p => { if (p.primary_goal_id === id) p.primary_goal_id = '' })
  draft.value.approved = draft.value.approved.filter(key => !key.startsWith(`${id}:`))
}
let pickerOpener: HTMLElement | null = null
async function showPicker(kind: 'pool' | 'replace' | 'add') {
  pickerKind.value = kind; page.value = 1
  pickerOpener = document.activeElement instanceof HTMLElement ? document.activeElement : null
  await nextTick()
  picker.value?.showModal()
  pickerSearch.value?.focus()
}
// 关闭弹层后把焦点还给触发按钮，键盘用户不会掉回页面开头。
function closePicker() {
  const opener = pickerOpener
  picker.value?.close()
  pickerOpener = null
  opener?.focus()
}
function togglePool(gid: string) {
  if (draft.value.selected.includes(gid) && draft.value.placements.some(p => p.gid === gid && p.lock)) { error.value = '请先解除该亲本的锁定。'; return }
  draft.value.selected = draft.value.selected.includes(gid) ? draft.value.selected.filter(id => id !== gid) : [...draft.value.selected, gid]
}
function choose(gid: string) {
  if (pickerKind.value === 'pool') { togglePool(gid); return }
  let positions = draft.value.placements.map(p => ({ ...p }))
  if (pickerKind.value === 'replace') {
    const old = selectedPosition.value
    if (!old || old.lock) { error.value = '请先解除该亲本的锁定。'; return }
    positions = positions.map(p => p.gid === old.gid ? { ...p, gid, primary_goal_id: '' } : p)
    if (mode.value === 'selected') draft.value.selected = draft.value.selected.map(id => id === old.gid ? gid : id)
  } else {
    const normal = positions.filter(p => p.kind === 'normal').length
    const kind = normal < draft.value.capacity ? 'normal' : draft.value.academy && !positions.some(p => p.kind === 'academy') ? 'academy' : null
    if (!kind) { error.value = '当前小窝容量已满，请先移出精灵或增加容量。'; return }
    const x = Math.max(-2, ...positions.map(p => p.x)) + 2
    if (x > 18) { error.value = '固定画布右侧已满，请先移出精灵或重新规划。'; return }
    positions.push({ gid, x, y: 0, kind, lock: '', primary_goal_id: '' })
  }
  if (mode.value === 'selected' && !draft.value.selected.includes(gid)) draft.value.selected.push(gid)
  selected.value = gid; closePicker(); model.edit(positions)
}
function updatePosition(values: Partial<Placement>) {
  if (!selectedPosition.value) return
  const current = selectedPosition.value
  if (current.lock === 'position' && ['x', 'y', 'kind'].some(k => k in values)) return
  model.edit(draft.value.placements.map(p => p.gid === selected.value ? { ...p, ...values } : { ...p }))
}
function cycleLock() {
  const lock = selectedPosition.value?.lock
  updatePosition({ lock: lock === '' ? 'participation' : lock === 'participation' ? 'position' : '' })
}
function removeParent() {
  if (selectedPosition.value?.lock) { error.value = '请先解除该亲本的锁定。'; return }
  model.edit(draft.value.placements.filter(p => p.gid !== selected.value)); selected.value = ''
}
function moveNest(gid: string, x: number, y: number, targetGid: string | null) {
  const first = draft.value.placements.find(p => p.gid === gid)
  const second = targetGid ? draft.value.placements.find(p => p.gid === targetGid) : undefined
  if (!first || (targetGid && !second)) return
  if (first.lock === 'position' || second?.lock === 'position') {
    error.value = '锁定位置的窝不能参与交换，请先解除位置锁定。'
    return
  }
  if (!second && first.x === x && first.y === y) return
  if (second) {
    model.edit(draft.value.placements.map(p => p.gid === first.gid ? { ...p, x: second.x, y: second.y, kind: second.kind }
      : p.gid === second.gid ? { ...p, x: first.x, y: first.y, kind: first.kind } : { ...p }))
    notice.value = `已交换 ${parentName(first.gid)} 与 ${parentName(second.gid)} 的窝位，正在重新评估布局。`
    return
  }
  model.edit(draft.value.placements.map(p => p.gid === first.gid ? { ...p, x, y } : { ...p }))
  notice.value = `已移动 ${parentName(first.gid)} 的窝位，正在重新评估布局。`
}
function swap(gid: string) {
  const target = draft.value.placements.find(p => p.gid === gid)
  if (target) moveNest(selected.value, target.x, target.y, gid)
}
function approve(key: string) {
  draft.value.approved = draft.value.approved.includes(key) ? draft.value.approved.filter(k => k !== key) : [...draft.value.approved, key]
}
function pause() { picker.value?.close(); pickerOpener = null; model.pause() }
function resetAccount() { pause(); selected.value = ''; model.resetAccount() }
onBeforeUnmount(pause)
defineExpose({ load: model.load, pause, resetAccount })
</script>

<template>
  <div class="planner-page" data-vue-page>
    <div class="planner-primary-column">
    <header class="planner-toolbar">
      <div class="planner-tabs" role="group" aria-label="配窝模式"><button :class="{ active: mode === 'target' }" :aria-pressed="mode === 'target'" @click="model.changeMode('target')"><UiIcon name="egg" /><span>按目标配窝</span></button><button :class="{ active: mode === 'selected' }" :aria-pressed="mode === 'selected'" @click="model.changeMode('selected')"><UiIcon name="backpack" /><span>自选精灵</span></button></div>
      <div class="planner-toolbar-actions">
        <button class="ghost-button" :disabled="!!busy || !context?.uid || !unsaved" :title="saveHint" aria-describedby="planner-save-hint" @click="model.save"><span>保存草稿</span></button>
        <small v-if="saveHint" id="planner-save-hint" class="planner-save-hint" role="status">{{ saveHint }}</small>
        <div class="planner-generate"><button class="planner-primary primary-button" :disabled="!model.canGenerate.value" @click="model.run('solve')"><UiIcon name="arrows-shuffle" /><span>{{ busy === 'solve' ? '正在规划…' : plan ? '重新规划' : '生成方案' }}</span></button><small v-if="generationHint" id="planner-generate-hint" role="status">{{ generationHint }}</small></div>
        <button class="ghost-button" :disabled="!!busy || !draft.placements.length" @click="model.clearPlan"><UiIcon name="trash" /><span>清除方案</span></button>
      </div>
    </header>
    <div v-if="error" class="planner-notice is-error" role="alert"><UiIcon name="alert-circle" />{{ error }}<button class="breeder-detail-link" :disabled="!!busy" @click="errorAction === 'save' ? model.save() : model.refresh()">{{ errorAction === 'save' ? '重试保存' : '刷新资料' }}</button></div>
    <div v-if="notice" class="planner-notice is-info" role="status"><UiIcon name="info-circle" />{{ notice }}</div>
    <main class="planner-main panel">
      <div class="planner-status" role="status"><span>{{ context?.source === 'history' ? '历史观察背包' : '当前账号已观察背包' }} · {{ context?.pet_count ?? '—' }} 只</span><span v-if="busy">{{ { loading: '正在读取资料', evaluate: '正在重评布局', saving: '正在保存', solve: '正在选择亲本与摆位' }[busy] }}</span><button v-else-if="dirty[mode]" class="planner-status-action planner-warning" :disabled="!!busy" @click="model.run('evaluate')">待重新评估 · 点击重评</button><span v-else>{{ statusName[plan?.status || result?.status || ''] || '尚未生成方案' }}</span><span v-if="plan" class="planner-status-progress">{{ mode === 'target' ? `目标就绪 ${plan.goals.filter(g => g.ready).length} / ${draft.goals.length}` : `${plan.edges.length} 组配对` }}</span></div>
      <div class="planner-scroll">
         <div class="planner-layout-heading"><div><strong>小窝布局</strong><small>{{ mode === 'target' ? '按培育条件选择亲本与窝位' : '分析所选精灵的配对关系与产物' }}</small></div><div v-if="draft.placements.length" class="planner-actions"><button class="ghost-button" :disabled="!!busy || !model.canUndo.value" title="撤销上一次窝位调整" @click="model.undo()">撤销</button><button class="ghost-button" :disabled="!!busy || !model.canRedo.value" title="重做被撤销的窝位调整" @click="model.undo(true)">重做</button><button v-if="model.canRestore.value" class="ghost-button" :disabled="!!busy" @click="model.restorePlan">恢复方案</button><button class="ghost-button" :disabled="!!busy" @click="model.run('evaluate')">重评布局</button><button class="ghost-button" :disabled="!context?.available || !!busy || mode === 'target' && !draft.goals.length" @click="showPicker('add')">补充布局亲本</button></div></div>
         <div v-if="plan || draft.placements.length" class="planner-summary" :class="{ 'is-stale': dirty[mode] }" aria-label="当前方案摘要"><div><small>当前入住亲本</small><strong>{{ placementCounts.males }} 父 / {{ placementCounts.females }} 母</strong></div><div><small>有配对的母本</small><strong>{{ plan ? `${plan.metrics.effective_mothers ?? 0} 只` : '待评估' }}</strong></div><div><small>{{ mode === 'target' ? '目标进度' : '配对关系' }}</small><strong>{{ plan ? mode === 'target' ? `${plan.goals.filter(g => g.ready).length} / ${draft.goals.length} 就绪` : `${plan.edges.length} 组` : mode === 'target' ? `${draft.goals.length} 项待评估` : '待评估' }}</strong></div><button v-if="plan" class="breeder-detail-link" @click="outcomes?.scrollIntoView({ block: 'start', behavior: 'smooth' })">{{ dirty[mode] ? '上次结果 · 待更新' : '查看产物详情 ↓' }}</button></div>
         <div v-if="result && result.plans.length > 1" class="planner-alternatives"><button v-for="(candidate, index) in result.plans" :key="candidate.plan_id" class="chip" :class="{ active: candidate === plan }" :aria-pressed="candidate === plan" :disabled="!!busy" @click="selected = ''; model.choosePlan(index)">{{ candidate.plan_id === 'previous' ? '原方案 · 对照' : `方案 ${index + 1}` }}<small>{{ candidate.metrics.males ?? 0 }} 父 / {{ candidate.metrics.females ?? 0 }} 母 · {{ candidate.edges.length }} 组配对<span v-if="mode === 'target'"> · {{ candidate.goals.filter(g => g.ready).length }} 目标就绪</span></small></button><span title="在有限搜索范围内比较候选，不保证全局最优">搜索范围内推荐 ⓘ</span></div>
         <BreedingCanvas v-if="draft.placements.length" :positions="draft.placements" :parents="parents" :plan="plan" :selected="selected" :pending="dirty[mode] || busy === 'evaluate'" @select="selected = $event" @move="moveNest" />
         <div v-else class="planner-empty planner-start"><UiIcon name="egg" /><strong>{{ mode === 'target' ? '从培育目标开始规划' : '选择精灵，分析配窝方案' }}</strong><p>{{ mode === 'target' ? '在右侧添加目标蛋，按需设置奖牌与性格，再生成方案。' : '在右侧选择参与精灵，确认参与方式与小窝容量，再生成方案。' }}</p><small>① {{ mode === 'target' ? '添加目标' : '选择精灵' }}　→　② 确认条件　→　③ 生成方案</small></div>
        <section v-if="selectedPosition" class="planner-resident">
          <header><strong>{{ parentName(selected) }}</strong><span>{{ selectedParent?.gender === 1 ? '父本' : '母本' }} · {{ selectedParent?.nature || '性格未知' }}</span><button class="breeder-detail-link" @click="host.openPet(selected)">背包详情</button></header>
          <div class="planner-actions"><button class="chip" :class="{ active: selectedPosition.lock }" :aria-pressed="!!selectedPosition.lock" @click="cycleLock">{{ { '': '未锁定', participation: '锁定参与', position: '锁定位置' }[selectedPosition.lock] }}</button><button class="ghost-button" :disabled="!!selectedPosition.lock" @click="showPicker('replace')">替换亲本</button><button class="ghost-button" :disabled="!!selectedPosition.lock" @click="removeParent">移出</button><select aria-label="交换到窝位" :value="''" :disabled="selectedPosition.lock === 'position'" @change="swap(($event.target as HTMLSelectElement).value)"><option value="">交换到另一窝位…</option><option v-for="pos in draft.placements.filter(p => p.gid !== selected && p.lock !== 'position')" :key="pos.gid" :value="pos.gid">{{ parentName(pos.gid) }} · {{ pos.kind === 'academy' ? '学院' : '普通' }}</option></select></div>
           <div v-if="mode === 'target' && selectedParent?.gender === 2" class="planner-coordinate"><label>母本主目标<select aria-label="母本主目标" :value="selectedPosition.primary_goal_id" @change="updatePosition({ primary_goal_id: ($event.target as HTMLSelectElement).value })"><option value="">自动分配主目标</option><option v-for="goal in draft.goals" :key="goal.goal_id" :value="goal.goal_id">{{ eggName(goal.egg_key) }} {{ goal.size_mark }} {{ goal.voice_mark }}</option></select></label></div>
        </section>
        <section v-if="plan || draft.placements.length" ref="outcomes" class="planner-outcomes" :class="{ 'is-stale': dirty[mode] }">
          <header><strong>产物与目标支持</strong><small>{{ dirty[mode] ? '下方为上次分析，等待重评' : '奖牌为规划支持，性格为模型参考' }}</small></header>
           <div v-if="!plan" class="planner-empty">
            <UiIcon name="egg" />
            <strong>{{ mode === 'target' ? '开始智能配窝规划' : '开始自选精灵配窝' }}</strong>
            <p v-if="mode === 'target'">在右侧「培育目标」区域点击蛋种添加目标，设置奖牌、性格等条件后，点击「生成方案」自动规划最优配对布局。</p>
            <p v-else>在右侧「参与精灵」区域选择想要配窝的精灵，选择参与方式后，点击「生成方案」自动分析配对关系与产物。</p>
          </div>
           <div v-if="mode === 'target' && plan?.status === 'no_plan' && draft.goals.some(g => !motherCounts.get(g.egg_key))" class="planner-notice is-warning">当前已观察背包中没有对应目标蛋的可繁育母本；请确认目标蛋、账号和背包采集记录。</div>
          <div v-for="goal in plan?.goals || []" :key="goal.goal_id" class="planner-goal-result" :class="{ 'planner-warning': !goal.ready }"><strong>{{ eggName(draft.goals.find(g => g.goal_id === goal.goal_id)?.egg_key || null) }}</strong><span>{{ goal.exact_mothers }} 合格主目标母本 · {{ goal.mother_count - goal.exact_mothers }} 迭代母本<span v-if="goal.shared_mothers"> · 另 {{ goal.shared_mothers }} 只母本可兼顾</span></span><small v-if="goal.reason">{{ goal.reason }}</small></div>
          <article v-for="mother in plan?.mothers || []" :key="mother.gid" class="planner-outcome" :class="mother.references.find(r => r.goal_id === mother.primary_goal_id)?.kind || 'unknown'">
            <header><strong>{{ eggName(mother.egg_key) }}</strong><button class="breeder-detail-link" @click="selected = mother.gid">{{ parentName(mother.gid) }} ♀</button><span class="chip">{{ mode === 'selected' ? '基础配对' : kindName[mother.references.find(r => r.goal_id === mother.primary_goal_id)?.kind || 'unknown'] }}</span></header>
            <p>{{ mother.fathers.length ? `范围内 ${mother.fathers.length} 个父本：${mother.fathers.map(parentName).join('、')}` : '尚无范围内兼容父本；只有蛋种参考' }}</p>
            <p v-if="mode === 'selected' && mother.fathers.length">共有奖牌参考：<template v-for="marks in markOutcomes(mother.gid)" :key="marks.join('＋')"><span v-if="marks.length" class="planner-mark-set"><MedalIcon v-for="mark in marks" :key="mark" :name="mark" /></span><span v-else>无共有奖牌参考</span></template></p><div v-for="reference in mother.references" :key="reference.goal_id" class="planner-reference"><span><strong>{{ reference.goal_id === mother.primary_goal_id ? '主目标' : '兼容目标' }}</strong> · 合格父本 <span class="planner-ratio" :title="`范围内父本共 ${reference.father_count} 个，其中 ${reference.matching_fathers} 个合格`"><strong>{{ reference.matching_fathers }}</strong><small>/{{ reference.father_count }}</small></span>{{ reference.iterative_fathers ? ` · 迭代 ${reference.iterative_fathers}` : '' }}</span><span v-if="draft.goals.find(g => g.goal_id === reference.goal_id)?.nature_id">目标奖牌＋性格已知贡献 <span class="planner-ratio"><strong>{{ percent(reference.nature_contribution) }}</strong></span> · 全父本性格 <span class="planner-ratio"><strong>{{ percent(reference.all_father_nature_contribution) }}</strong></span></span><small v-if="reference.interference.length" class="planner-warning">迭代或目标干扰父本：{{ reference.interference.map(parentName).join('、') }}</small></div>
            <div class="planner-edge-details"><details><summary>逐父本奖牌与性格参考</summary><p v-for="edge in plan?.edges.filter(e => e.female === mother.gid)" :key="edge.male">{{ parentName(edge.male) }}：共有 {{ edge.marks.join('＋') || '无奖牌' }}；<span v-for="(share, name) in edge.nature.known" :key="name">{{ name }} {{ percent(share) }} </span><span v-if="edge.nature.random">随机 {{ percent(edge.nature.random) }} </span><span v-if="edge.nature.unknown">未知 {{ percent(edge.nature.unknown) }}</span></p></details><span>全父本等权参考：<span v-for="(share, name) in mother.nature.known" :key="name">{{ name }} {{ percent(share) }} </span>随机 {{ percent(mother.nature.random) }} · 未知 {{ percent(mother.nature.unknown) }}</span></div>
          </article>
          <div v-if="plan?.metrics.unused_slots" class="planner-notice is-info">保留 {{ plan.metrics.unused_slots }} 个空窝：{{ mode === 'selected' && draft.selected.length === draft.placements.length ? '所选精灵已全部入住，剩余容量保留空窝。' : '当前有界方案未找到更多目标收益，可调整亲本或布局。' }}</div>
          <div v-for="issue in issues" :key="issue" class="planner-notice is-warning">{{ issue }}</div>
          <details v-if="plan?.unused_candidates.length"><summary>未采用的自选精灵（{{ plan.unused_candidates.length }}）</summary><p v-for="item in unusedRows" :key="item.gid">{{ parentName(item.gid) }} · …{{ item.gid.slice(-6) }}：{{ item.reason }}</p><div class="planner-actions"><button class="ghost-button" :disabled="currentUnusedPage <= 1" @click="unusedPage = currentUnusedPage - 1">上一页</button><span>{{ currentUnusedPage }} / {{ unusedPages }}</span><button class="ghost-button" :disabled="currentUnusedPage >= unusedPages" @click="unusedPage = currentUnusedPage + 1">下一页</button></div></details>
        </section>
      </div>
    </main>
    </div>
    <aside class="planner-sidebar panel">
      <header><span class="planner-sidebar-title-icon"><UiIcon :name="mode === 'target' ? 'flag' : 'users'" /></span><strong>{{ mode === 'target' ? '培育目标' : '参与精灵' }}</strong></header>
      <div class="planner-sidebar-scroll">
        <section class="planner-capacity">
          <div>
            <label>普通小窝 <select v-model.number="draft.capacity" aria-label="普通小窝数量"><option v-for="count in 11" :key="count" :value="count - 1">{{ count - 1 }} 个</option></select></label>
            <label><input v-model="draft.academy" type="checkbox">学院绿窝 +1</label>
          </div>
          <small>本次规划容量 · {{ draft.capacity + Number(draft.academy) }} 窝</small>
        </section>
        <template v-if="mode === 'target'">
           <div class="planner-section-title"><strong>添加目标蛋</strong><small>点击添加 · 最多 30 个</small></div>
           <input v-model="eggSearch" type="search" class="planner-search" placeholder="搜索蛋名或蛋组，点击添加" aria-label="查找目标蛋">
           <div class="planner-egg-choices"><button v-for="egg in visibleEggChoices" :key="egg.egg_key" type="button" :disabled="draft.goals.length >= 30" @click="addGoal(egg.egg_key)"><img :src="egg.icon_url" alt="" @error="($event.target as HTMLImageElement).style.visibility = 'hidden'"><span><strong>{{ egg.name }}</strong><small>{{ egg.groups.join(' / ') }} · 已观察母本 {{ motherCounts.get(egg.egg_key) || 0 }} 只</small></span><span aria-hidden="true">＋</span></button><p v-if="!eggChoices.length" class="planner-muted">没有匹配的目标蛋</p></div>
           <small v-if="eggChoices.length > 24" class="planner-muted">仅显示前 24 项，搜索蛋名可查找其他目标。</small>
           <div v-if="!draft.goals.length" class="planner-sidebar-empty">点击上方目标蛋即可添加；奖牌、性格默认不限。</div>
          <div v-if="draft.goals.length" class="planner-section-title planner-configured-title"><strong>已添加目标</strong><span class="count-badge">{{ draft.goals.length }}</span></div>
          <article v-for="(goal, index) in draft.goals" :key="goal.goal_id" class="planner-goal-editor">
            <header><span class="count-badge">{{ index + 1 }}</span><strong>{{ eggName(goal.egg_key) }}</strong><button class="ghost-button" :aria-label="`移除目标${index + 1}`" @click="removeGoal(goal.goal_id)"><UiIcon name="x" /></button></header>
             <p class="planner-goal-summary">{{ goalSummary(goal) }}</p>
             <small :class="{ 'planner-warning': !motherCounts.get(goal.egg_key) }">{{ motherCounts.get(goal.egg_key) ? `可用母本 ${motherCounts.get(goal.egg_key)} 只` : '未观察到对应母本，请核对背包资料' }}</small>
             <details class="planner-goal-options"><summary>编辑目标与附加条件</summary>
               <label class="planner-egg-replace">目标蛋<select :value="goal.egg_key" @change="changeGoal(goal, ($event.target as HTMLSelectElement).value)"><option v-for="egg in context?.eggs" :key="egg.egg_key" :value="egg.egg_key">{{ egg.name }}</option></select><small>更换蛋种保留奖牌、性格和优先级，需重新选择迭代亲本。</small></label>
               <div class="planner-goal-pair"><label>体型奖牌<select v-model="goal.size_mark"><option value="">不限</option><option>大块头</option><option>小不点</option></select></label><label>声音奖牌<select v-model="goal.voice_mark"><option value="">不限</option><option>婉转声</option><option>粗嗓门</option></select></label></div>
               <div class="planner-goal-pair"><label>目标性格<select v-model.number="goal.nature_id"><option :value="0">不限</option><option v-for="n in context?.natures" :key="n.id" :value="n.id">{{ n.name }}</option></select></label><label>优先级<select v-model.number="goal.priority"><option :value="0">普通</option><option :value="1">优先</option></select></label></div>
             </details>
          </article>
        </template>
        <template v-else>
          <div class="planner-section-title"><strong>参与精灵</strong><span class="count-badge">{{ draft.selected.length }}</span></div>
          <button class="planner-add-pool ghost-button" :disabled="!context?.available || !!busy" @click="showPicker('pool')">{{ draft.selected.length ? '管理参与精灵' : '＋ 选择参与精灵' }}</button>
          <label class="planner-participation">参与方式<select v-model="draft.participation"><option value="best">择优参与</option><option value="all">全部参与</option></select></label>
          <p class="planner-participation-help">{{ draft.participation === 'best' ? '从已选精灵中挑选配对，可保留空窝；未采用原因会列在结果中。' : '尝试让全部所选精灵入住；容量不足或不兼容时会在结果中说明。' }}</p>
          <p v-if="draft.participation === 'all' && draft.selected.length > draft.capacity + Number(draft.academy)" class="planner-warning planner-participation-help" role="status">已选 {{ draft.selected.length }} 只，超过 {{ draft.capacity + Number(draft.academy) }} 窝容量；请增加容量或减少选择。</p>
          <p v-if="plan" class="planner-participation-help">{{ dirty[mode] ? '待重新规划 · ' : '' }}当前布局采用 {{ selectedInPlan }} / {{ draft.selected.length }} 只所选精灵</p>
          <div v-if="draft.selected.length" class="planner-picked"><div v-for="gid in selectedRows" :key="gid" class="planner-picked-row"><span :title="`个体 ${gid}`"><strong>{{ parentName(gid) }}</strong><small>…{{ gid.slice(-6) }} · {{ !plan || dirty[mode] ? '待规划' : placedIds.has(gid) ? '已采用' : '未采用' }}</small></span><button class="ghost-button" :aria-label="`移除 ${parentName(gid)}，个体 ${gid}`" @click="togglePool(gid)"><UiIcon name="x" /></button></div></div>
          <p v-else class="planner-participation-help">尚未选择精灵。可按性别、性格、蛋组和奖牌筛选。</p>
          <div v-if="selectedPages > 1" class="planner-actions"><button class="ghost-button" :disabled="currentSelectedPage <= 1" @click="selectedPage = currentSelectedPage - 1">上一页</button><span>{{ currentSelectedPage }} / {{ selectedPages }}</span><button class="ghost-button" :disabled="currentSelectedPage >= selectedPages" @click="selectedPage = currentSelectedPage + 1">下一页</button></div>
        </template>
        <section v-if="relevantIterations.length && mode === 'target'" class="planner-iterations">
          <header><strong>迭代候选</strong><small>先选择，点击生成后纳入方案</small></header>
          <div class="planner-actions"><button class="ghost-button" :disabled="currentIterationPage <= 1" @click="iterationPage = currentIterationPage - 1">上一页</button><small>{{ currentIterationPage }} / {{ iterationPages }} · 已准许 {{ draft.approved.length }} 组</small><button class="ghost-button" :disabled="currentIterationPage >= iterationPages" @click="iterationPage = currentIterationPage + 1">下一页</button></div><article v-for="item in iterationRows" :key="item.key" :class="item.kind === 'unknown' ? 'unknown' : 'iterative'">
            <header><strong>{{ eggName(draft.goals.find(g => g.goal_id === item.goal_id)?.egg_key || null) }}</strong><span>{{ item.kind === 'unknown' ? '缺少原始数据' : '迭代参考' }}</span></header><p>{{ parentName(item.female) }} ♀ × {{ parentName(item.male) }} ♂</p><small :title="`母本个体 ${item.female} / 父本个体 ${item.male}`">母本 …{{ item.female.slice(-6) }} · {{ parents.get(item.female)?.nature || '性格未知' }} / 父本 …{{ item.male.slice(-6) }} · {{ parents.get(item.male)?.nature || '性格未知' }}</small><p class="planner-iteration-marks"><span v-for="mark in item.missing_marks" :key="mark" class="planner-iteration-slot" :title="`${mark} 位置当前为空位，需在后代中培养`">{{ mark }}<small>待培养</small></span> · {{ item.candidate_voice === null ? item.candidate_weight_ratio === null ? '原始值未知' : `自身目录体重位置 ${percent(item.candidate_weight_ratio)}` : `${item.candidate_voice} dB` }}</p><small>{{ item.candidate_weight === null ? '' : `待培养亲本：${item.candidate_species} · ${(item.candidate_weight / 1000).toFixed(3)} kg。` }}{{ item.evidence }}，不代表本代可达。</small><label v-if="item.kind === 'iterative'"><input type="checkbox" :checked="draft.approved.includes(item.key)" @change="approve(item.key)">用此亲本迭代</label>
          </article>
          <button class="planner-primary" :disabled="!draft.approved.length || !model.canGenerate.value" @click="model.run('solve')">生成迭代方案</button>
        </section>
        <details class="planner-rules">
          <summary>规则与参考边界</summary>
          <ul>
            <li>摆位是工具草图规则：20×20 格、每窝占 2×2、中心吸附半格，手动坐标限 0～18 格，仅视图居中不改草稿坐标。</li>
            <li>画布连线表示奖牌支持：实线为合格支持、虚线为干扰；父本 30%＋母本 30%＋随机 40% 是模型参考，不是实测保证。</li>
            <li>搜索有节点与时间预算，只返回已验证的较优布局，不宣称全局最优。</li>
            <li>迭代候选只表示方向接近，不代表后代可达；勾选准许后才会纳入求解。</li>
          </ul>
          <p>规则 {{ context?.rule_version || '—' }} · 几何 {{ context?.geometry_version || '—' }} · 目录 {{ context?.catalog_version || '—' }}{{ result ? ` · 本次搜索${result.search_status === 'bounded' ? '达预算（bounded）' : '未运行'}` : '' }}</p>
        </details>
      </div>
    </aside>
    <dialog ref="picker" class="planner-picker" aria-labelledby="planner-picker-title" aria-modal="true" @click="($event.target === picker) && closePicker()">
      <header><strong id="planner-picker-title">{{ pickerKind === 'pool' ? '选择参与配窝的精灵' : pickerKind === 'replace' ? '替换当前亲本' : '添加亲本到布局' }}</strong><button class="ghost-button" aria-label="关闭选择精灵" @click="closePicker()"><UiIcon name="x" /></button></header>
      <div class="planner-picker-filters"><input ref="pickerSearch" v-model="search" type="search" placeholder="名称、性格、蛋组或个体ID" aria-label="查找候选精灵" @input="page = 1"><select v-model="gender" aria-label="候选性别" @change="page = 1"><option value="">全部性别</option><option value="1">父本</option><option value="2">母本</option></select><select v-model="nature" aria-label="候选性格" @change="page = 1"><option value="">全部性格</option><option v-for="n in context?.natures" :key="n.id">{{ n.name }}</option></select><select v-model="group" aria-label="候选蛋组" @change="page = 1"><option value="">全部蛋组</option><option v-for="name in currentGroups" :key="name">{{ name }}</option></select><select v-model="medal" aria-label="候选奖牌" @change="page = 1"><option value="">全部奖牌</option><option v-for="name in ['大块头', '小不点', '婉转声', '粗嗓门']" :key="name">{{ name }}</option></select></div>
      <div class="planner-picker-grid"><BreederCard v-for="parent in pickerRows" :key="parent.gid" :parent="parent" :selected="pickerKind === 'pool' && draft.selected.includes(parent.gid)" @select="choose(parent.gid)" @open="closePicker(); host.openPet($event)" /><div v-if="!pickerRows.length" class="planner-empty">当前观察记录中没有符合筛选的候选。</div></div>
      <footer><span>已选择 {{ draft.selected.length }} 只 · {{ filtered.length }} 个候选</span><div class="planner-actions"><button class="ghost-button" :disabled="page <= 1" @click="page--">上一页</button><span>{{ page }} / {{ Math.max(1, Math.ceil(filtered.length / 24)) }}</span><button class="ghost-button" :disabled="page * 24 >= filtered.length" @click="page++">下一页</button><button class="planner-primary" @click="closePicker()">完成</button></div></footer>
    </dialog>
  </div>
</template>
