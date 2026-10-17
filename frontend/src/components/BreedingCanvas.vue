<script setup lang="ts">
import { computed, ref } from 'vue'
import type { BreederParent } from '../types/breederLibrary'
import type { Placement, Plan } from '../types/breedingPlanner'

const props = defineProps<{ positions: Placement[]; parents: Map<string, BreederParent>; plan: Plan | null; pending: boolean; selected: string }>()
const emit = defineEmits<{ select: [gid: string]; move: [gid: string, x: number, y: number, targetGid: string | null] }>()
const drag = ref<{ gid: string; x: number; y: number; moved: boolean; cellX: number; cellY: number } | null>(null)
const hint = ref('')
const outside = computed(() => props.positions.some(p => p.x < 0 || p.x > 18 || p.y < 0 || p.y > 18))
// 固定显示整块 20×20 棋盘（20 格 × 32px）：不随内容平移或缩放；
// 只有旧草稿带越界坐标时才扩大到包住内容，避免窝位被裁掉。
const boardSize = 640
const boardBounds = computed(() => {
  if (!outside.value) return { x: 0, y: 0, size: boardSize }
  const xs = props.positions.map(position => position.x * 32 + 32)
  const ys = props.positions.map(position => position.y * 32 + 32)
  const minX = Math.min(0, ...xs), maxX = Math.max(boardSize - 32, ...xs)
  const minY = Math.min(0, ...ys), maxY = Math.max(boardSize - 32, ...ys)
  const size = Math.max(boardSize, maxX - minX + 128, maxY - minY + 128)
  return { x: (minX + maxX - size) / 2, y: (minY + maxY - size) / 2, size }
})
// 连线和说明以格子中心为准；拖动中的窝跟随指针位置。
function center(gid: string) {
  const position = props.positions.find(item => item.gid === gid)
  const x = drag.value?.gid === gid ? drag.value.cellX : position?.x
  const y = drag.value?.gid === gid ? drag.value.cellY : position?.y
  return x === undefined || y === undefined ? null : { x: x * 32 + 32, y: y * 32 + 32 }
}
const links = computed(() => (props.plan?.edges || []).flatMap(edge => {
  const male = center(edge.male), female = center(edge.female)
  if (!male || !female) return []
  const interference = (props.plan?.mothers || []).some(mother => mother.gid === edge.female && mother.references.some(reference => reference.interference.includes(edge.male)))
  const dim = !!props.selected && props.selected !== edge.male && props.selected !== edge.female
  return [{ key: `${edge.male}:${edge.female}`, male, female, interference, dim }]
}))
const connected = computed(() => new Set((props.plan?.edges || []).flatMap(edge => [edge.male, edge.female])))
const caption = computed(() => {
  if (!props.positions.length) return '还没有小窝。生成方案或补充亲本后，这里会显示 20×20 草图内的窝位。'
  const academy = props.positions.filter(position => position.kind === 'academy').length
  const nests = `共 ${props.positions.length} 个小窝（普通 ${props.positions.length - academy}／学院 ${academy}），按 2×2 占地、中心吸附半格摆放。`
  if (!props.plan) return `${nests}拖动窝位可移到空位或与另一窝交换，也可用方向键移动、Enter 选择。`
  const interference = links.value.filter(link => link.interference).length
  return `${nests}${props.pending ? '布局已改动，正在重新评估…' : `当前 ${links.value.length} 条父本连线${interference ? `，其中 ${interference} 条为干扰连边（虚线）` : ''}。`}拖动窝位可交换，也可用方向键移动、Enter 选择。`
})

// 2×2 占地下，间距小于 2 格视为重叠。
function overlapped(gid: string, x: number, y: number) {
  return props.positions.some(position => position.gid !== gid && Math.abs(position.x - x) < 2 && Math.abs(position.y - y) < 2)
}
function pointerDown(event: PointerEvent, gid: string) {
  if (event.button !== 0 || props.positions.find(p => p.gid === gid)?.lock === 'position') return
  ;(event.currentTarget as SVGGElement).setPointerCapture(event.pointerId)
  const position = props.positions.find(p => p.gid === gid)!
  drag.value = { gid, x: event.clientX, y: event.clientY, moved: false, cellX: position.x, cellY: position.y }
}
function pointerMove(event: PointerEvent) {
  if (!drag.value) return
  const svg = (event.currentTarget as SVGGElement).ownerSVGElement
  const matrix = svg?.getScreenCTM()
  if (!svg || !matrix) return
  const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse())
  drag.value.cellX = Math.max(0, Math.min(18, Math.round((point.x - 32) / 32)))
  drag.value.cellY = Math.max(0, Math.min(18, Math.round((point.y - 32) / 32)))
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
const steps: Record<string, [number, number]> = { ArrowLeft: [-2, 0], ArrowRight: [2, 0], ArrowUp: [0, -2], ArrowDown: [0, 2] }
function key(event: KeyboardEvent, gid: string) {
  if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); emit('select', gid); return }
  const step = steps[event.key]
  if (!step) return
  event.preventDefault()
  if (event.repeat) return
  const position = props.positions.find(item => item.gid === gid)
  if (!position || position.lock === 'position') return
  const x = Math.max(0, Math.min(18, position.x + step[0]))
  const y = Math.max(0, Math.min(18, position.y + step[1]))
  if (x === position.x && y === position.y) return
  if (overlapped(gid, x, y)) { hint.value = '该位置与已有小窝重叠，已保持原位。'; return }
  hint.value = ''
  emit('select', gid)
  emit('move', gid, x, y, null)
}
</script>
<template>
  <div class="planner-canvas-view">
    <div class="planner-canvas">
      <svg :viewBox="`${boardBounds.x} ${boardBounds.y} ${boardBounds.size} ${boardBounds.size}`" preserveAspectRatio="xMidYMid meet" aria-label="小窝布局草图">
        <defs><pattern id="planner-grid" width="32" height="32" patternUnits="userSpaceOnUse"><path d="M32 0H0V32" class="planner-grid-line" fill="none" /></pattern></defs>
        <rect :x="boardBounds.x" :y="boardBounds.y" :width="boardBounds.size" :height="boardBounds.size" fill="url(#planner-grid)" />
        <rect :x="0" :y="0" :width="boardSize" :height="boardSize" class="planner-board-border" fill="none" />
        <g v-if="!pending" class="planner-canvas-links" aria-hidden="true"><line v-for="link in links" :key="link.key" class="planner-edge" :class="{ interference: link.interference, dim: link.dim }" :x1="link.male.x" :y1="link.male.y" :x2="link.female.x" :y2="link.female.y" /></g>
        <g v-for="(position, index) in positions" :key="position.gid" class="planner-nest" :class="[{ selected: selected === position.gid, academy: position.kind === 'academy', dragging: drag?.gid === position.gid, unrelated: !!plan && !connected.has(position.gid) }, `gender-${parents.get(position.gid)?.gender}`]"
          :transform="`translate(${(drag?.gid === position.gid ? drag.cellX : position.x) * 32 + 32},${(drag?.gid === position.gid ? drag.cellY : position.y) * 32 + 32})`" :data-gid="position.gid" tabindex="0" role="button" :aria-label="`${index + 1}号，${parents.get(position.gid)?.name || '当前记录未找到'}，${parents.get(position.gid)?.gender === 1 ? '父本' : '母本'}${position.lock ? '，已锁定' : ''}，方向键移动，Enter 选择，也可拖动到空位或与另一窝交换位置`"
          @focus="emit('select', position.gid)" @pointerdown="pointerDown($event, position.gid)" @pointermove="pointerMove" @pointerup="pointerUp" @pointercancel="drag = null" @keydown="key($event, position.gid)">
          <rect x="-32" y="-32" width="64" height="64" rx="8" />
          <text x="-25" y="-17" class="planner-nest-number">{{ index + 1 }}</text>
          <text x="25" y="-17" text-anchor="end" class="planner-nest-gender">{{ parents.get(position.gid)?.gender === 1 ? '♂' : '♀' }}</text>
          <g v-if="position.kind === 'academy'" class="planner-nest-badge" transform="translate(-22,22)"><circle r="9" /><text y="4" text-anchor="middle">学</text><title>学院绿窝</title></g>
          <g v-if="position.lock" class="planner-nest-badge is-lock" transform="translate(22,22)"><circle r="9" /><text y="4" text-anchor="middle">锁</text><title>{{ position.lock === 'position' ? '位置锁定：不能拖动或换位' : '参与锁定：保持在本方案中' }}</title></g>
          <image v-if="parents.get(position.gid)?.icon_url" :href="parents.get(position.gid)!.icon_url" x="-22" y="-8" width="44" height="44" preserveAspectRatio="xMidYMid meet" />
        </g>
      </svg>
    </div>
    <div v-if="positions.length" class="planner-canvas-key" aria-label="小窝亲本索引">
      <button v-for="(position, index) in positions" :key="position.gid" type="button" :class="{ active: selected === position.gid }" :aria-pressed="selected === position.gid" @click="emit('select', position.gid)">
        <span>{{ index + 1 }}<i :class="parents.get(position.gid)?.gender === 1 ? 'male' : 'female'">{{ parents.get(position.gid)?.gender === 1 ? '♂' : '♀' }}</i></span>
        <img v-if="parents.get(position.gid)?.icon_url" :src="parents.get(position.gid)!.icon_url" alt="" loading="lazy">
        <strong>{{ parents.get(position.gid)?.name || '记录缺失' }}</strong>
        <small>{{ position.kind === 'academy' ? '学院窝' : '普通窝' }}</small>
      </button>
    </div>
    <p class="planner-canvas-caption" role="status"><span v-if="hint" class="planner-warning">{{ hint }}　</span>{{ caption }}<span v-if="links.length && !pending" class="planner-canvas-legend"><i class="planner-legend-swatch" />合格支持<i class="planner-legend-swatch is-interference" />干扰连边</span></p>
    <p v-if="outside" class="planner-canvas-outside">草稿中有窝位超出 20×20 草图范围，请重新规划或调整位置。</p>
  </div>
</template>
