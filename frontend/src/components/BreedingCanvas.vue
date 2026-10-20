<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import MedalIcon from './MedalIcon.vue'
import UiIcon from './UiIcon.vue'
import type { BreederParent } from '../types/breederLibrary'
import type { Placement, Plan } from '../types/breedingPlanner'

const props = defineProps<{ positions: Placement[]; parents: Map<string, BreederParent>; plan: Plan | null; pending: boolean; selected: string }>()
const emit = defineEmits<{ select: [gid: string]; move: [gid: string, x: number, y: number, targetGid: string | null]; locate: [gid: string] }>()
const drag = ref<{ gid: string; x: number; y: number; moved: boolean; cellX: number; cellY: number } | null>(null)
const hint = ref('')
const canvasElement = ref<HTMLElement | null>(null)
const canvasHeight = ref(0)
let canvasObserver: ResizeObserver | null = null
const BOARD_MIN = -18
const BOARD_MAX = 18
const outside = computed(() => props.positions.some(p => p.x < BOARD_MIN || p.x > BOARD_MAX || p.y < BOARD_MIN || p.y > BOARD_MAX))
const canvasStyle = computed(() => canvasHeight.value ? { '--planner-canvas-height': `${canvasHeight.value}px` } : undefined)
// 硬性规定：配窝预览（窝群）必须显示在画布中间，且不能小到看不清。
// 视口以窝群包围盒中心为中心、格距固定 32 单位（一格 1 格）；视口越小窝越大，
// 因此视口按窝群自适应（小窝群也收到 VIEW_MIN），只有越界旧草稿才继续扩大视口。
const boardSize = 640
const VIEW_MIN = 400   // 少窝时的最小视口：保证窝不小于画布的 1/7
const VIEW_PAD = 96    // 窝群四周留白，避免窝位贴着画布边缘
const boardBounds = computed(() => {
  if (!props.positions.length) return { x: 0, y: 0, size: boardSize }
  const xs = props.positions.map(position => position.x * 32 + 32)
  const ys = props.positions.map(position => position.y * 32 + 32)
  const minX = Math.min(...xs), maxX = Math.max(...xs)
  const minY = Math.min(...ys), maxY = Math.max(...ys)
  const size = Math.round(Math.max(VIEW_MIN, maxX - minX + VIEW_PAD, maxY - minY + VIEW_PAD))
  return { x: Math.round((minX + maxX - size) / 2), y: Math.round((minY + maxY - size) / 2), size }
})
onMounted(() => {
  if (typeof ResizeObserver === 'undefined' || !canvasElement.value) return
  const syncCanvasHeight = () => { canvasHeight.value = Math.round(canvasElement.value!.getBoundingClientRect().height) }
  canvasObserver = new ResizeObserver(syncCanvasHeight)
  canvasObserver.observe(canvasElement.value)
  syncCanvasHeight()
})
onBeforeUnmount(() => canvasObserver?.disconnect())
// 连线和说明以格子中心为准；拖动中的窝跟随指针位置。
function center(gid: string) {
  const position = props.positions.find(item => item.gid === gid)
  const x = drag.value?.gid === gid ? drag.value.cellX : position?.x
  const y = drag.value?.gid === gid ? drag.value.cellY : position?.y
  return x === undefined || y === undefined ? null : { x: x * 32 + 32, y: y * 32 + 32 }
}
function insetPoint(from: { x: number; y: number }, to: { x: number; y: number }, distance = 28) {
  const dx = to.x - from.x, dy = to.y - from.y
  const length = Math.hypot(dx, dy)
  if (!length) return from
  return { x: from.x + dx / length * distance, y: from.y + dy / length * distance }
}
const links = computed(() => (props.plan?.edges || []).flatMap(edge => {
  const male = center(edge.male), female = center(edge.female)
  if (!male || !female) return []
  const start = insetPoint(male, female), end = insetPoint(female, male)
  const interference = (props.plan?.mothers || []).some(mother => mother.gid === edge.female && mother.references.some(reference => reference.interference.includes(edge.male)))
  const dim = !!props.selected && props.selected !== edge.male && props.selected !== edge.female
  return [{ key: `${edge.male}:${edge.female}`, x1: start.x, y1: start.y, x2: end.x, y2: end.y, interference, dim }]
}))
const connected = computed(() => new Set((props.plan?.edges || []).flatMap(edge => [edge.male, edge.female])))
const selectedPosition = computed(() => props.positions.find(position => position.gid === props.selected) || null)
const selectedCenter = computed(() => selectedPosition.value ? center(selectedPosition.value.gid) : null)
const shortName = (gid: string) => {
  const name = props.parents.get(gid)?.name || '记录缺失'
  return name.length > 5 ? `${name.slice(0, 5)}…` : name
}
const locationLabel = (gid: string) => {
  const location = props.parents.get(gid)?.location
  return location ? `第${location.box_id}箱·第${location.row}行第${location.column}列` : '位置未采集'
}
const displayMarkNames = new Set(['大块头', '小不点', '粗嗓门', '婉转声'])
const parentMarks = (gid: string) => Array.from(new Set(props.parents.get(gid)?.marks.filter(mark => displayMarkNames.has(mark.name)).map(mark => mark.name) || []))
const caption = computed(() => {
  if (!props.positions.length) return '还没有小窝。生成方案或补充亲本后，这里会显示 20×20 草图内的窝位。'
  const academy = props.positions.filter(position => position.kind === 'academy').length
  const nests = `共 ${props.positions.length} 个小窝（普通 ${props.positions.length - academy}／学院 ${academy}），按 2×2 占地、中心吸附半格摆放。`
  if (!props.plan) return `${nests}拖动窝位可移到空位或与另一窝交换，Enter 选择。`
  const interference = links.value.filter(link => link.interference).length
  return `${nests}${props.pending ? '布局已改动，正在重新评估…' : `当前 ${links.value.length} 条父本连线${interference ? `，其中 ${interference} 条为干扰连边（虚线）` : ''}。`}拖动窝位可交换，Enter 选择。`
})

// 2×2 占地下，间距小于 2 格视为重叠。
function overlapped(gid: string, x: number, y: number) {
  return props.positions.some(position => position.gid !== gid && Math.abs(position.x - x) < 2 && Math.abs(position.y - y) < 2)
}
const dropState = computed(() => {
  if (!drag.value?.moved) return null
  const target = props.positions.find(position => position.gid !== drag.value!.gid && position.x === drag.value!.cellX && position.y === drag.value!.cellY)
  if (target) return { type: 'swap' as const, targetGid: target.gid, x: drag.value.cellX, y: drag.value.cellY }
  return {
    type: overlapped(drag.value.gid, drag.value.cellX, drag.value.cellY) ? 'blocked' as const : 'valid' as const,
    targetGid: null,
    x: drag.value.cellX,
    y: drag.value.cellY,
  }
})
function pointerDown(event: PointerEvent, gid: string) {
  if (event.button !== 0 || props.positions.find(p => p.gid === gid)?.lock === 'position') return
  ;(event.currentTarget as SVGGElement).setPointerCapture(event.pointerId)
  const position = props.positions.find(p => p.gid === gid)!
  drag.value = { gid, x: event.clientX, y: event.clientY, moved: false, cellX: position.x, cellY: position.y }
}
function pointerMove(event: PointerEvent) {
  if (!drag.value) return
  const svg = (event.currentTarget as SVGGElement).ownerSVGElement
  if (!svg) return
  const rect = svg.getBoundingClientRect()
  const bounds = boardBounds.value
  const scale = Math.min(rect.width / bounds.size, rect.height / bounds.size)
  if (!scale) return
  const offsetX = (rect.width - bounds.size * scale) / 2
  const offsetY = (rect.height - bounds.size * scale) / 2
  const pointX = bounds.x + (event.clientX - rect.left - offsetX) / scale
  const pointY = bounds.y + (event.clientY - rect.top - offsetY) / scale
  drag.value.cellX = Math.max(BOARD_MIN, Math.min(BOARD_MAX, Math.round((pointX - 32) / 32)))
  drag.value.cellY = Math.max(BOARD_MIN, Math.min(BOARD_MAX, Math.round((pointY - 32) / 32)))
  if (Math.hypot(event.clientX - drag.value.x, event.clientY - drag.value.y) > 5) drag.value.moved = true
}
function pointerUp() {
  if (!drag.value) return
  const current = drag.value
  drag.value = null
  emit('select', current.gid)
  if (!current.moved) return
  const target = props.positions.find(position => position.gid !== current.gid && position.x === current.cellX && position.y === current.cellY)
  if (target) { hint.value = ''; emit('move', current.gid, current.cellX, current.cellY, target.gid); return }
  if (overlapped(current.gid, current.cellX, current.cellY)) { hint.value = '该位置与已有小窝重叠，已保持原位。'; return }
  hint.value = ''
  emit('move', current.gid, current.cellX, current.cellY, null)
}
function key(event: KeyboardEvent, gid: string) {
  if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); emit('select', gid); return }
}
</script>
<template>
  <div class="planner-canvas-view" :style="canvasStyle">
    <div ref="canvasElement" class="planner-canvas">
      <svg :viewBox="`${boardBounds.x} ${boardBounds.y} ${boardBounds.size} ${boardBounds.size}`" preserveAspectRatio="xMidYMid meet" aria-label="小窝布局草图">
        <defs><pattern id="planner-grid" width="32" height="32" patternUnits="userSpaceOnUse"><path d="M32 0H0V32" class="planner-grid-line" fill="none" /></pattern></defs>
        <rect class="planner-board-grid" :x="boardBounds.x" :y="boardBounds.y" :width="boardBounds.size" :height="boardBounds.size" fill="url(#planner-grid)" />
        <g v-for="(position, index) in positions" :key="position.gid" class="planner-nest" :class="[{ selected: selected === position.gid, academy: position.kind === 'academy', dragging: drag?.gid === position.gid, 'drop-target': dropState?.targetGid === position.gid, unrelated: !!plan && !connected.has(position.gid) }, `gender-${parents.get(position.gid)?.gender}`]"
          :transform="`translate(${(drag?.gid === position.gid ? drag.cellX : position.x) * 32 + 32},${(drag?.gid === position.gid ? drag.cellY : position.y) * 32 + 32})`" :data-gid="position.gid" tabindex="0" role="button" :aria-label="`${index + 1}号，${parents.get(position.gid)?.name || '当前记录未找到'}，${parents.get(position.gid)?.gender === 1 ? '父本' : '母本'}${position.lock ? '，已锁定' : ''}，Enter 选择，也可拖动到空位或与另一窝交换位置`"
          @focus="emit('select', position.gid)" @pointerdown="pointerDown($event, position.gid)" @pointermove="pointerMove" @pointerup="pointerUp" @pointercancel="drag = null" @keydown="key($event, position.gid)">
          <rect x="-32" y="-32" width="64" height="64" rx="8" />
          <title>{{ parents.get(position.gid)?.name || '记录缺失' }}</title>
          <text x="-25" y="-17" class="planner-nest-number">{{ index + 1 }}</text>
          <svg x="16" y="-29" width="16" height="16" viewBox="0 0 24 24" class="planner-nest-gender" aria-hidden="true">
            <use :href="`/static/icons/sprite.svg#${parents.get(position.gid)?.gender === 1 ? 'gender-male' : 'gender-female'}`" width="24" height="24" />
          </svg>
          <image v-if="parents.get(position.gid)?.icon_url" :href="parents.get(position.gid)!.icon_url" x="-22" y="-8" width="44" height="44" preserveAspectRatio="xMidYMid meet" />
          <g v-if="position.kind === 'academy'" class="planner-nest-badge is-academy" transform="translate(-31,18)"><rect width="34" height="14" rx="7" /><text x="17" y="10" text-anchor="middle">学院</text><title>学院绿窝：必须放母本，性格 100% 遗传母本</title></g>
          <g v-if="position.lock" class="planner-nest-badge is-lock" transform="translate(22,22)"><circle r="9" /><text y="4" text-anchor="middle">锁</text><title>{{ position.lock === 'position' ? '位置锁定：不能拖动或换位' : '参与锁定：保持在本方案中' }}</title></g>
          <g class="planner-nest-name" aria-hidden="true"><rect x="-30" y="34" width="60" height="16" rx="8" /><text x="0" y="45" text-anchor="middle">{{ shortName(position.gid) }}</text></g>
        </g>
        <g v-if="!pending" class="planner-canvas-links" aria-hidden="true"><line v-for="link in links" :key="link.key" class="planner-edge" :class="{ interference: link.interference, dim: link.dim }" :x1="link.x1" :y1="link.y1" :x2="link.x2" :y2="link.y2" /></g>
        <g v-if="selectedCenter" class="planner-selected-outline" :transform="`translate(${selectedCenter.x},${selectedCenter.y})`" aria-hidden="true"><rect x="-32" y="-32" width="64" height="64" rx="8" /></g>
        <g v-if="dropState" class="planner-drop-preview" :class="`is-${dropState.type}`" :transform="`translate(${dropState.x * 32 + 32},${dropState.y * 32 + 32})`" aria-hidden="true"><rect x="-32" y="-32" width="64" height="64" rx="8" /></g>
      </svg>
    </div>
    <div v-if="positions.length" class="planner-canvas-key" aria-label="小窝亲本索引">
      <div v-for="(position, index) in positions" :key="position.gid" class="planner-canvas-key-item">
        <button type="button" class="planner-canvas-key-select" :class="[{ active: selected === position.gid }, `gender-${parents.get(position.gid)?.gender}`]" :aria-pressed="selected === position.gid" @click="emit('select', position.gid)">
          <span>{{ index + 1 }}</span>
          <img v-if="parents.get(position.gid)?.icon_url" :src="parents.get(position.gid)!.icon_url" alt="" loading="lazy">
          <strong class="planner-canvas-key-name" :title="[parents.get(position.gid)?.name || '记录缺失', parents.get(position.gid)?.gender === 1 ? '父本' : '母本', ...parentMarks(position.gid), position.kind === 'academy' ? '学院窝' : '普通窝', parents.get(position.gid)?.nature || '性格未知'].join(' · ')">
            <span class="planner-canvas-key-label">{{ parents.get(position.gid)?.name || '记录缺失' }}</span>
            <span class="planner-canvas-key-gender" :class="parents.get(position.gid)?.gender === 1 ? 'male' : 'female'" :aria-label="parents.get(position.gid)?.gender === 1 ? '父本' : '母本'"><UiIcon :name="parents.get(position.gid)?.gender === 1 ? 'gender-male' : 'gender-female'" /></span>
            <span v-for="mark in parentMarks(position.gid)" :key="mark" class="planner-canvas-key-mark" :title="mark"><MedalIcon :name="mark" /></span>
          </strong>
          <small>{{ position.kind === 'academy' ? '学院窝' : '普通窝' }}　{{ parents.get(position.gid)?.nature || '性格未知' }}</small>
        </button>
        <div class="planner-canvas-key-actions">
          <button type="button" class="planner-canvas-key-locate" :aria-label="`定位${parents.get(position.gid)?.name || '当前精灵'}`" title="在游戏箱位中定位此精灵" @click="emit('locate', position.gid)">定位精灵</button>
          <span class="planner-canvas-key-location" :title="locationLabel(position.gid)">{{ locationLabel(position.gid) }}</span>
        </div>
      </div>
    </div>
    <p class="planner-canvas-caption" role="status"><span v-if="hint" class="planner-warning">{{ hint }}　</span>{{ caption }}<span v-if="links.length && !pending" class="planner-canvas-legend"><i class="planner-legend-swatch" />合格支持<i class="planner-legend-swatch is-interference" />干扰连边</span></p>
    <p v-if="outside" class="planner-canvas-outside">草稿中有窝位超出 20×20 草图范围，请重新规划或调整位置。</p>
  </div>
</template>
