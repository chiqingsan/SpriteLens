<script setup lang="ts">
import { computed } from 'vue'
import { nearbyAttentionTone, type NearbyAttention, type NearbyActor, type NearbySnapshot } from '../types/nearby'
const props = withDefaults(defineProps<{ data: NearbySnapshot | null; selected?: string; compact?: boolean; radius?: number; note?: string }>(), {
  radius: 10000,
  note: '',
})
const emit = defineEmits<{ select: [id: string] }>()

/** 固定 400×400 参考坐标系：圆心 200、外环屏显半径 180；所有文字标签都必须留在 viewBox 内。 */
const VIEW_SIZE = 400
const CENTER = VIEW_SIZE / 2
const OUTER_RADIUS = 180
const RING_RADII = [60, 120, 180] as const
const LABEL_MARGIN = 4
/** 默认只标注最近 6 个目标，避免密集场景标签互相遮挡。 */
const LABEL_LIMIT = 6
const LABEL_FONT_SIZE = 9
const SELECTED_FONT_SIZE = 10

interface RadarRow {
  actor: NearbyActor
  kind: NearbyAttention
  dx: number
  dy: number
  distance: number
  x: number
  y: number
  attentionTone: number
  label: string
}
interface Box { left: number; right: number; top: number; bottom: number }
interface LabelPlacement {
  id: string
  text: string
  anchor: 'start' | 'end'
  x: number
  y: number
  fontSize: number
  rect: { x: number; y: number; width: number; height: number }
  selected: boolean
}

function labelFor(name: string, actorId: string, compact: boolean) {
  const value = name.trim() || `精灵 ${actorId.slice(-4)}`
  const maxLength = compact ? 4 : 8
  return value.length > maxLength ? `${value.slice(0, maxLength)}…` : value
}
/** 刻度值：>=1000 折算成 k 并去掉尾零，<1000 保留原始数值。 */
function formatScaleValue(value: number) {
  const rounded = Math.max(1, Math.round(value))
  if (rounded < 1000) return String(rounded)
  const scaled = Math.round(rounded / 100) / 10
  return `${Number.isInteger(scaled) ? scaled : scaled.toFixed(1)}k`
}
/** 粗估文本宽度：CJK 记满字号，其余字符约 0.56 字号，用于标签占位与越界判断。 */
function estimateTextWidth(text: string, fontSize: number) {
  let width = 0
  for (const char of text) width += char.charCodeAt(0) > 0x2e80 ? fontSize : fontSize * 0.56
  return width
}
/**
 * 把标签放在点位外侧，并在越界时翻到另一侧后夹回 viewBox；
 * 与已占用矩形冲突时返回 null（选中目标先占位，其次按距离，最后是同名聚合标签）。
 */
function placeLabel(point: { x: number; y: number }, text: string, fontSize: number, occupied: Box[]) {
  const width = estimateTextWidth(text, fontSize) + 6
  const height = fontSize + 4
  const chipTopOffset = -Math.round(fontSize * 1.1)
  const gap = 9
  const preferredAnchor: 'start' | 'end' = point.x < CENTER ? 'end' : 'start'
  const anchorOn = (anchor: 'start' | 'end') => anchor === 'start' ? point.x + gap : point.x - gap - width
  let anchor = preferredAnchor
  let chipX = anchorOn(anchor)
  if (chipX < LABEL_MARGIN || chipX + width > VIEW_SIZE - LABEL_MARGIN) {
    const flipped: 'start' | 'end' = preferredAnchor === 'start' ? 'end' : 'start'
    const flippedX = anchorOn(flipped)
    if (flippedX >= LABEL_MARGIN && flippedX + width <= VIEW_SIZE - LABEL_MARGIN) {
      anchor = flipped
      chipX = flippedX
    } else {
      chipX = Math.min(Math.max(chipX, LABEL_MARGIN), Math.max(LABEL_MARGIN, VIEW_SIZE - LABEL_MARGIN - width))
    }
  }
  let baseline = point.y + (point.y < CENTER ? -8 : 15)
  let chipTop = baseline + chipTopOffset
  if (chipTop < LABEL_MARGIN) baseline += LABEL_MARGIN - chipTop
  else if (chipTop + height > VIEW_SIZE - LABEL_MARGIN) baseline -= chipTop + height - (VIEW_SIZE - LABEL_MARGIN)
  chipTop = baseline + chipTopOffset
  const box: Box = { left: chipX - 1, right: chipX + width + 1, top: chipTop - 1, bottom: chipTop + height + 1 }
  if (occupied.some(other => box.left < other.right && box.right > other.left && box.top < other.bottom && box.bottom > other.top)) return null
  occupied.push(box)
  return {
    text,
    anchor,
    x: anchor === 'start' ? chipX + 3 : chipX + width - 3,
    y: baseline,
    fontSize,
    rect: { x: chipX, y: chipTop, width, height },
  }
}
const range = computed(() => Number.isFinite(props.radius) && props.radius > 0 ? props.radius : 10000)
/** 三环刻度：外环 = 半径、中环 = 半径/2、内环 = 半径/5；放在右下方避开十字轴与中心标签。 */
const scale = computed(() => [
  { key: 'outer', radius: OUTER_RADIUS, value: range.value },
  { key: 'middle', radius: 120, value: range.value / 2 },
  { key: 'inner', radius: 60, value: range.value / 5 },
].map(tick => ({
  ...tick,
  text: formatScaleValue(tick.value),
  x: CENTER + tick.radius * Math.SQRT1_2,
  y: CENTER + tick.radius * Math.SQRT1_2 + 4,
})))
const projection = computed(() => {
  const center = props.data?.player_position
  const originX = center?.[0]
  const originY = center?.[1]
  if (originX == null || originY == null) return null
  const rows: RadarRow[] = (props.data?.actors || []).flatMap(actor => {
    const position = actor.position
    const px = position?.[0]
    const py = position?.[1]
    if (px == null || py == null) return []
    const dx = px - originX
    const dy = py - originY
    return [{
      actor,
      kind: actor.attention,
      dx,
      dy,
      distance: Math.hypot(dx, dy),
      x: CENTER + dx / range.value * OUTER_RADIUS,
      y: CENTER + dy / range.value * OUTER_RADIUS,
      attentionTone: nearbyAttentionTone(actor.actor_id),
      label: labelFor(actor.name, actor.actor_id, Boolean(props.compact) && props.selected !== actor.actor_id),
    }]
  })
  // 只绘制本次观察半径内的目标，半径之外的目标既不显示点位也不显示标签。
  const visibleRows = rows.filter(row => row.distance <= range.value)
  const byDistance = [...visibleRows].sort((a, b) => a.distance - b.distance || a.actor.actor_id.localeCompare(b.actor.actor_id))
  const selectedRow = visibleRows.find(row => row.actor.actor_id === props.selected) ?? null
  const labels: LabelPlacement[] = []
  const occupied: Box[] = []
  function addLabel(row: RadarRow, text: string, fontSize: number, selected = false) {
    const placement = placeLabel({ x: row.x, y: row.y }, text, fontSize, occupied)
    if (placement) labels.push({ ...placement, id: row.actor.actor_id, selected })
  }
  // 选中的目标永远优先占位，即使它不在最近 6 个里。
  if (selectedRow) addLabel(selectedRow, selectedRow.label, SELECTED_FONT_SIZE, true)
  // compact 模式只保留选中目标的名称；完整模式只给单牌/双牌标注名称（普通点不加文字），同名合并成「名称 ×N」。
  if (!props.compact) {
    const nearest = byDistance.filter(row => row.actor.actor_id !== selectedRow?.actor.actor_id && row.kind !== 'normal').slice(0, LABEL_LIMIT)
    const groups = new Map<string, RadarRow[]>()
    for (const row of nearest) {
      const key = row.actor.name.trim() || row.actor.actor_id
      const group = groups.get(key)
      if (group) group.push(row)
      else groups.set(key, [row])
    }
    for (const group of groups.values()) {
      const anchorRow = group[0]!
      addLabel(anchorRow, group.length > 1 ? `${anchorRow.label} ×${group.length}` : anchorRow.label, LABEL_FONT_SIZE)
    }
  }
  return { range: range.value, rows: visibleRows, labels }
})
</script>
<template>
  <section class="scene-radar" :class="{ 'is-overlay': compact }" aria-label="附近精灵雷达">
    <header><strong>场景雷达</strong><span v-if="projection">{{ data?.position_source === 'client_target' ? '以移动目标位置为参考' : data?.position_source === 'teleport' ? '以传送落点为参考' : '以已观察位置为参考' }}</span></header>
    <div v-if="!compact && projection" class="radar-legend" aria-label="雷达目标图例"><span><i class="radar-legend-dot" />普通</span><span><i class="radar-legend-dot is-marked" />单牌</span><span><i class="radar-legend-dot is-double" />双牌</span></div>
    <div class="radar-body">
      <svg viewBox="0 0 400 400" preserveAspectRatio="xMidYMid meet" class="scene-radar-scope" role="group" aria-label="参考坐标雷达">
        <circle v-for="radius in RING_RADII" :key="radius" cx="200" cy="200" :r="radius" class="radar-ring" />
        <path d="M20 200H380M200 20V380" class="radar-axis" />
        <g v-if="!compact" class="radar-scale" aria-hidden="true"><text v-for="tick in scale" :key="tick.key" class="radar-scale-label" :x="tick.x" :y="tick.y" text-anchor="middle">{{ tick.text }}</text></g>
        <g v-if="projection">
          <g class="radar-center"><path class="radar-player-cross" d="M194 200H206M200 194V206" /><circle cx="200" cy="200" r="5" class="radar-player" /></g>
          <g v-for="row in projection.rows" :key="row.actor.actor_id" class="radar-target" :class="[`is-${row.kind}`, `attention-tone-${row.attentionTone}`, { selected: selected === row.actor.actor_id }]" :transform="`translate(${row.x},${row.y})`" tabindex="0" role="button" :aria-label="`${row.actor.name}${row.kind === 'double' ? '，双牌' : row.kind === 'marked' ? '，单牌' : ''}`" @click="emit('select', row.actor.actor_id)" @keydown.enter="emit('select', row.actor.actor_id)" @keydown.space.prevent="emit('select', row.actor.actor_id)">
            <title>{{ row.actor.name }} · {{ row.kind === 'double' ? '双牌' : row.kind === 'marked' ? '单牌' : '普通' }} · Lv.{{ row.actor.level ?? '未知' }}</title><circle r="12" class="radar-hit"/><circle v-if="row.kind !== 'normal'" r="10" class="radar-attention-ring" /><circle :r="row.kind === 'double' ? 7 : row.kind === 'marked' ? 6 : 5" class="radar-point" />
          </g>
          <g v-for="label in projection.labels" :key="`label-${label.id}`" class="radar-label" :class="{ selected: label.selected }" aria-hidden="true">
            <rect class="radar-label-bg" :x="label.rect.x" :y="label.rect.y" :width="label.rect.width" :height="label.rect.height" rx="3" /><text class="radar-target-label" :x="label.x" :y="label.y" :text-anchor="label.anchor">{{ label.text }}</text>
          </g>
        </g>
        <text v-else x="200" y="200" text-anchor="middle">等待玩家位置</text>
      </svg>
    </div>
    <template v-if="!compact">
      <p v-if="note" class="radar-note">{{ note }}</p>
      <p v-if="projection">外环 {{ projection.range.toLocaleString('zh-CN') }} 单位 · 已定位 {{ projection.rows.length }} / {{ data?.actors.length ?? 0 }} · 原始坐标，未校准米制</p>
    </template>
  </section>
</template>
<style scoped>
/* 场景雷达：面板模式是白底浮卡，compact 模式嵌进悬浮雷达的深色浮层。 */
.scene-radar { display: flex; flex-direction: column; height: 100%; min-width: 0; min-height: 0; max-width: 100%; padding: var(--space-4); border: 1px solid var(--line-soft); border-radius: var(--radius-lg); background: var(--panel); color: var(--ink); }
.scene-radar header { display: flex; flex: none; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: var(--space-1) var(--space-3); min-width: 0; }
.scene-radar header strong { color: var(--ink); font-size: var(--fs-sm); font-weight: 600; }
.scene-radar header span { min-width: 0; color: var(--muted); font-size: var(--fs-3xs); overflow-wrap: anywhere; }
.radar-legend { display: flex; flex: none; flex-wrap: wrap; gap: var(--space-3); margin-top: var(--space-2); color: var(--muted); font-size: var(--fs-3xs); }
.radar-legend > span { display: inline-flex; align-items: center; gap: var(--space-1); }
.radar-legend-dot { width: 8px; height: 8px; flex: none; border-radius: 50%; background: var(--teal); }
.radar-legend-dot.is-marked { background: var(--amber); }
.radar-legend-dot.is-double { width: 10px; height: 10px; border: 1px solid var(--danger-ink); background: var(--danger); }
.radar-body { display: grid; flex: 1 1 0; place-items: center; min-width: 0; min-height: 0; margin: var(--space-2) 0; }
.scene-radar-scope { display: block; width: 100%; height: 100%; max-width: 100%; max-height: 100%; border-radius: var(--radius-md); background: var(--surface-1); box-shadow: inset 0 0 0 1px var(--line-soft); }
.radar-ring, .radar-axis { fill: none; stroke: var(--line); stroke-width: 1; }
.radar-ring { stroke-dasharray: 2 4; }
.radar-axis { stroke-dasharray: 4 5; }
/* 字号不要写在 .scene-radar text 上：它比 .radar-target-label 的类选择器优先级高，
   会把标签算好的 9px 底片撑破。空态提示单独给字号。 */
.scene-radar text { fill: var(--muted); }
.scene-radar-scope > text { font-size: 11px; }
.radar-scale-label { fill: var(--muted-2); font-size: 10px; font-weight: 500; }
.radar-player-cross { fill: none; stroke: var(--ink); stroke-width: 1.5; stroke-linecap: round; }
.radar-player { fill: var(--ink); stroke: var(--panel); stroke-width: 2; }
.radar-target { cursor: pointer; outline: none; }
.radar-hit { fill: transparent; }
.radar-attention-ring { fill: none; stroke-width: 2.5; }
.radar-target.attention-tone-0 .radar-attention-ring { stroke: var(--radar-attention-0); }
.radar-target.attention-tone-1 .radar-attention-ring { stroke: var(--radar-attention-1); }
.radar-target.attention-tone-2 .radar-attention-ring { stroke: var(--radar-attention-2); }
.radar-target.attention-tone-3 .radar-attention-ring { stroke: var(--radar-attention-3); }
.radar-target.attention-tone-4 .radar-attention-ring { stroke: var(--radar-attention-4); }
.radar-point { fill: var(--teal); stroke: var(--panel); stroke-width: 2; }
.radar-target.is-marked .radar-point { fill: var(--amber); }
.radar-target.is-double .radar-point { fill: var(--danger); stroke-width: 2.5; }
.radar-target:hover .radar-hit { fill: color-mix(in srgb, var(--teal) 10%, transparent); }
.radar-target:focus-visible .radar-hit,
.radar-target.selected .radar-hit { fill: color-mix(in srgb, var(--teal) 16%, transparent); stroke: var(--teal); stroke-width: 1.5; }
.radar-label { pointer-events: none; }
.radar-label-bg { fill: var(--panel); fill-opacity: .86; }
.radar-label.selected .radar-label-bg { fill-opacity: .98; }
.radar-target-label { fill: var(--ink); font-size: 9px; font-weight: 600; }
.radar-label.selected .radar-target-label { fill: var(--teal-deep); font-size: 10px; }
.scene-radar > p { flex: none; margin: 0; color: var(--muted); font-size: var(--fs-3xs); line-height: 1.5; overflow-wrap: anywhere; }
.scene-radar > .radar-note { margin-top: var(--space-2); padding-top: var(--space-2); border-top: 1px solid var(--line-soft); }

.scene-radar.is-overlay { flex: 1; min-height: 0; padding: 0; border: 0; border-radius: 0; background: transparent; }
.is-overlay header { display: none; }
.is-overlay .radar-body { margin: 0; }
.is-overlay .scene-radar-scope { border-radius: 0; background: transparent; box-shadow: none; }
.is-overlay .radar-ring, .is-overlay .radar-axis { stroke: var(--radar-overlay-line); }
.is-overlay .scene-radar text { fill: var(--radar-overlay-muted); }
.is-overlay .radar-player { fill: var(--radar-overlay-ink); stroke: var(--radar-overlay-bg); }
.is-overlay .radar-player-cross { stroke: var(--radar-overlay-ink); }
.is-overlay .radar-point { fill: var(--radar-overlay-point); stroke: var(--radar-overlay-bg); }
.is-overlay .radar-target.is-marked .radar-point { fill: var(--amber-bright); }
.is-overlay .radar-target.is-double .radar-point { fill: var(--danger); stroke: var(--radar-overlay-bg); }
.is-overlay .radar-target-label { fill: var(--radar-overlay-ink); }
.is-overlay .radar-label.selected .radar-target-label { fill: var(--radar-overlay-ink); }
.is-overlay .radar-label-bg { fill: var(--radar-overlay-bg); fill-opacity: .85; }
.is-overlay .radar-target:hover .radar-hit { fill: color-mix(in srgb, var(--radar-overlay-point) 16%, transparent); }
.is-overlay .radar-target.selected .radar-hit,
.is-overlay .radar-target:focus-visible .radar-hit { fill: color-mix(in srgb, var(--radar-overlay-point) 22%, transparent); stroke: var(--radar-overlay-point); }

/* SVG 字号是用户单位，会随画布等比缩放。.radar-target-label 的底片几何由脚本按
   9px/10px 用户单位算好，CSS 改字号会让文字溢出底片并被 viewBox 裁掉，所以只补偿
   不受几何约束的文字（空态提示、刻度值）。 */
.is-overlay .scene-radar-scope > text { font-size: 16px; }

@media (max-width: 1200px) {
  .scene-radar:not(.is-overlay) .radar-scale-label { font-size: 13px; }
  .scene-radar:not(.is-overlay) .scene-radar-scope > text { font-size: 15px; }
}
</style>
