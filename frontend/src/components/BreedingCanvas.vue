<script setup lang="ts">
import { computed, ref } from 'vue'
import type { BreederParent } from '../types/breederLibrary'
import type { Placement, Plan } from '../types/breedingPlanner'

const props = defineProps<{ positions: Placement[]; parents: Map<string, BreederParent>; plan: Plan | null; pending: boolean; selected: string }>()
const emit = defineEmits<{ select: [gid: string]; move: [gid: string, x: number, y: number, targetGid: string | null] }>()
const drag = ref<{ gid: string; x: number; y: number; moved: boolean; cellX: number; cellY: number } | null>(null)
const outside = computed(() => props.positions.some(p => p.x < 0 || p.x > 18 || p.y < 0 || p.y > 18))
const boardBounds = computed(() => {
  if (!props.positions.length) return { x: 0, y: 0, size: 640 }
  const xs = props.positions.map(position => position.x * 32 + 32)
  const ys = props.positions.map(position => position.y * 32 + 32)
  const minX = Math.min(...xs), maxX = Math.max(...xs)
  const minY = Math.min(...ys), maxY = Math.max(...ys)
  const size = Math.max(256, maxX - minX + 128, maxY - minY + 128)
  return { x: (minX + maxX - size) / 2, y: (minY + maxY - size) / 2, size }
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
  const matrix = svg?.getScreenCTM()
  if (!svg || !matrix) return
  const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse())
  drag.value.cellX = Math.max(0, Math.min(18, Math.round((point.x - 32) / 32)))
  drag.value.cellY = Math.max(0, Math.min(18, Math.round((point.y - 32) / 32)))
  if (Math.hypot(event.clientX - drag.value.x, event.clientY - drag.value.y) > 5) drag.value.moved = true
}
function pointerUp(event: PointerEvent) {
  if (!drag.value) return
  const current = drag.value
  drag.value = null
  if (current.moved) {
    const target = props.positions.find(position => position.gid !== current.gid && position.x === current.cellX && position.y === current.cellY)
    emit('select', current.gid)
    emit('move', current.gid, current.cellX, current.cellY, target?.gid || null)
    return
  }
  emit('select', current.gid)
}
function key(event: KeyboardEvent, gid: string) {
  if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); emit('select', gid) }
}
</script>
<template>
  <div class="planner-canvas-view">
    <div class="planner-canvas">
      <svg :viewBox="`${boardBounds.x} ${boardBounds.y} ${boardBounds.size} ${boardBounds.size}`" preserveAspectRatio="xMidYMid meet" aria-label="小窝布局草图">
        <defs><pattern id="planner-grid" width="32" height="32" patternUnits="userSpaceOnUse"><path d="M32 0H0V32" class="planner-grid-line" fill="none" /></pattern></defs>
        <rect :x="boardBounds.x" :y="boardBounds.y" :width="boardBounds.size" :height="boardBounds.size" fill="url(#planner-grid)" />
        <g v-for="(position, index) in positions" :key="position.gid" class="planner-nest" :class="[{ selected: selected === position.gid, academy: position.kind === 'academy', dragging: drag?.gid === position.gid }, `gender-${parents.get(position.gid)?.gender}`]"
          :transform="`translate(${(drag?.gid === position.gid ? drag.cellX : position.x) * 32 + 32},${(drag?.gid === position.gid ? drag.cellY : position.y) * 32 + 32})`" :data-gid="position.gid" tabindex="0" role="button" :aria-label="`${index + 1}号，${parents.get(position.gid)?.name || '当前记录未找到'}，${parents.get(position.gid)?.gender === 1 ? '父本' : '母本'}${position.lock ? '，已锁定' : ''}，按住拖动可移动到空位或与另一窝交换位置`"
          @focus="emit('select', position.gid)" @pointerdown="pointerDown($event, position.gid)" @pointermove="pointerMove" @pointerup="pointerUp($event)" @pointercancel="drag = null" @keydown="key($event, position.gid)">
          <rect x="-32" y="-32" width="64" height="64" rx="8" />
          <text x="-25" y="-17" class="planner-nest-number">{{ index + 1 }}</text>
          <text x="25" y="-17" text-anchor="end" class="planner-nest-gender">{{ parents.get(position.gid)?.gender === 1 ? '♂' : '♀' }}</text>
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
    <p v-if="outside" class="planner-canvas-outside">草稿中有窝位超出 20×20 草图范围，请重新规划或调整位置。</p>
  </div>
</template>
