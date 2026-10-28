<script setup lang="ts">
import { computed, useId } from 'vue'
import UiIcon from './UiIcon.vue'
import MapCoverage from './MapCoverage.vue'
import type { WorldMapEntry } from '../types/worldMap'
import { nearbyAttentionTone, type NearbyAttention, type NearbyActor, type NearbySnapshot } from '../types/nearby'
const props = withDefaults(defineProps<{ data: NearbySnapshot | null; map?: WorldMapEntry | null; selected?: string; compact?: boolean; radius?: number; note?: string; visible?: boolean }>(), {
  radius: 10000,
  note: '',
  visible: true,
})
const emit = defineEmits<{ select: [id: string] }>()
const mapClipId = `radar-map-${useId()}`

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
/**
 * 密集场景渲染预算：雷达最多为 MAX_RENDERED_TARGETS 个目标建可交互节点（每点 3~4 个 SVG 节点）。
 * 只裁渲染不改数据：左侧列表仍展示完整实体，超限说明见页脚。
 */
const MAX_RENDERED_TARGETS = 160

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
/** 原始坐标 → 米：1 原始单位 ≈ 1 cm（大陆现场校准，见 docs/NEARBY_MAP_PLAN_2026-10-26.md §米制比例尺）。 */
function formatMeters(raw: number) {
  const meters = raw / 100
  return `${meters >= 10 ? Math.round(meters) : Math.round(meters * 10) / 10} m`
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
/** 覆盖归属校验：只画当前账号、当前地图的足迹；切号/切图残留的旧包不画，也不报错。 */
const visibleCoverage = computed(() => {
  const data = props.data
  const coverage = data?.coverage
  if (!data || !coverage || coverage.uid !== data.uid) return null
  return data.resource_id === null || coverage.map_id === data.resource_id ? coverage : null
})
/**
 * 渲染预算：选中项优先，其次非普通关注，再按距玩家距离由近到远，取前 MAX_RENDERED_TARGETS 个；
 * 返回保持 actors 原始顺序，避免推送时节点顺序跳动。只裁渲染，不改数据。
 */
function budgetRows(rows: RadarRow[], selectedId?: string) {
  if (rows.length <= MAX_RENDERED_TARGETS) return rows
  const keep = new Set<string>()
  const selected = rows.find(row => row.actor.actor_id === selectedId)
  if (selected) keep.add(selected.actor.actor_id)
  const ranked = [...rows].sort((a, b) => (a.kind === 'normal' ? 1 : 0) - (b.kind === 'normal' ? 1 : 0)
    || a.distance - b.distance || a.actor.actor_id.localeCompare(b.actor.actor_id))
  for (const row of ranked) {
    if (keep.size >= MAX_RENDERED_TARGETS) break
    keep.add(row.actor.actor_id)
  }
  return rows.filter(row => keep.has(row.actor.actor_id))
}
const range = computed(() => Number.isFinite(props.radius) && props.radius > 0 ? props.radius : 10000)
const mapBackground = computed(() => {
  const map = props.map, position = props.data?.player_position
  if (!map || position?.[0] == null || position[1] == null) return null
  const scale = OUTER_RADIUS / range.value
  return {
    x: CENTER + (map.projection.origin_x - position[0]) * scale,
    y: CENTER + (map.projection.origin_y - position[1]) * scale,
    width: map.projection.side * scale,
    height: map.projection.side * scale,
  }
})
/** 三环刻度：外环 = 半径、中环 = 半径/2、内环 = 半径/5；放在右下方避开十字轴与中心标签。 */
const scale = computed(() => [
  { key: 'outer', radius: OUTER_RADIUS, value: range.value },
  { key: 'middle', radius: 120, value: range.value / 2 },
  { key: 'inner', radius: 60, value: range.value / 5 },
].map(tick => ({
  ...tick,
  text: formatMeters(tick.value),
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
  const renderedRows = budgetRows(visibleRows, props.selected)
  const byDistance = [...renderedRows].sort((a, b) => a.distance - b.distance || a.actor.actor_id.localeCompare(b.actor.actor_id))
  const selectedRow = renderedRows.find(row => row.actor.actor_id === props.selected) ?? null
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
  return { range: range.value, rows: renderedRows, labels, total: visibleRows.length }
})
// 调试坐标：仅当后端按环境变量打开时显示原始 x/y，供现场地标校准；不参与雷达投影。
// 只显示二维 x/y：校准用不到高度 z，少一行文案也能让窄窗圆盘保留可见高度。
const debugPosition = computed(() => {
  const data = props.data
  if (!data?.debug_coordinates || !Array.isArray(data.player_position)) return ''
  const [x, y] = data.player_position
  if (typeof x !== 'number' || typeof y !== 'number') return ''
  return `原始坐标 x=${x} y=${y}`
})
</script>
<template>
  <section class="scene-radar" :class="{ 'is-overlay': compact }" aria-label="附近精灵雷达">
    <header><strong>场景雷达</strong><span v-if="projection">{{ data?.position_source === 'client_target' ? '以移动目标位置为参考' : data?.position_source === 'teleport' ? '以传送落点为参考' : '以已观察位置为参考' }}</span></header>
    <div v-if="!compact && projection" class="radar-legend" aria-label="雷达目标图例"><span><i class="radar-legend-dot" />普通</span><span><i class="radar-legend-dot is-marked" />单牌</span><span><i class="radar-legend-dot is-double" />双牌</span></div>
    <div class="radar-body">
      <svg viewBox="0 0 400 400" preserveAspectRatio="xMidYMid meet" class="scene-radar-scope" role="group" aria-label="参考坐标雷达">
        <defs><clipPath :id="mapClipId"><rect width="400" height="400" :rx="compact ? 10 : 0" /></clipPath></defs>
        <g v-if="map && mapBackground" :clip-path="`url(#${mapClipId})`" class="radar-map">
          <image :href="map.image.url" :x="mapBackground.x" :y="mapBackground.y" :width="mapBackground.width" :height="mapBackground.height" preserveAspectRatio="none" />
          <g v-if="visible" :transform="`translate(${mapBackground.x},${mapBackground.y}) scale(${mapBackground.width / map.image.width},${mapBackground.height / map.image.height})`"><MapCoverage :coverage="visibleCoverage" :map="map" /></g>
        </g>
        <circle v-for="radius in RING_RADII" :key="radius" cx="200" cy="200" :r="radius" class="radar-ring" />
        <path d="M20 200H380M200 20V380" class="radar-axis" />
        <g v-if="!compact" class="radar-scale" aria-hidden="true"><text v-for="tick in scale" :key="tick.key" class="radar-scale-label" :x="tick.x" :y="tick.y" text-anchor="middle">{{ tick.text }}</text></g>
        <g v-if="projection">
          <g v-for="row in projection.rows" :key="row.actor.actor_id" class="radar-target" :class="[`is-${row.kind}`, `attention-tone-${row.attentionTone}`, { selected: selected === row.actor.actor_id }]" :transform="`translate(${row.x},${row.y})`" tabindex="0" role="button" :aria-label="`${row.actor.name}${row.kind === 'double' ? '，双牌' : row.kind === 'marked' ? '，单牌' : ''}`" @click="emit('select', row.actor.actor_id)" @keydown.enter="emit('select', row.actor.actor_id)" @keydown.space.prevent="emit('select', row.actor.actor_id)">
            <title>{{ row.actor.name }} · {{ row.kind === 'double' ? '双牌' : row.kind === 'marked' ? '单牌' : '普通' }} · Lv.{{ row.actor.level ?? '未知' }}</title><circle r="12" class="radar-hit"/><circle v-if="row.kind !== 'normal'" r="10" class="radar-attention-ring" /><circle :r="row.kind === 'double' ? 7 : row.kind === 'marked' ? 6 : 5" class="radar-point" />
          </g>
          <g v-for="label in projection.labels" :key="`label-${label.id}`" class="radar-label" :class="{ selected: label.selected }" aria-hidden="true">
            <rect class="radar-label-bg" :x="label.rect.x" :y="label.rect.y" :width="label.rect.width" :height="label.rect.height" rx="3" /><text class="radar-target-label" :x="label.x" :y="label.y" :text-anchor="label.anchor">{{ label.text }}</text>
          </g>
          <g class="radar-center"><circle cx="200" cy="200" r="8" class="radar-player" /><UiIcon name="current-location" x="193" y="193" width="14" height="14" class="radar-player-icon" /><text v-if="!compact" x="200" y="220" text-anchor="middle" class="radar-self-label">{{ data?.position_source === 'client_target' ? '你的移动目标' : '你的位置' }}</text></g>
        </g>
        <text v-else x="200" y="200" text-anchor="middle">等待玩家位置</text>
      </svg>
    </div>
    <p v-if="compact && debugPosition" class="radar-debug is-compact">{{ debugPosition }}</p>
    <template v-if="!compact">
      <p v-if="note" class="radar-note">{{ note }}</p>
      <p v-if="debugPosition" class="radar-debug">{{ debugPosition }}</p>
      <p v-if="projection" class="radar-footnote"><span>外环 {{ projection.range.toLocaleString('zh-CN') }} 单位 ≈ {{ formatMeters(projection.range) }}</span><span> · </span><span>已定位 {{ projection.total }} / {{ data?.actors.length ?? 0 }}</span><span> · </span><span>按 1 单位 ≈ 1 cm 折算</span><span>（大陆现场校准，平面距离）</span><template v-if="projection.total > projection.rows.length"><span> · </span><span>显示 {{ projection.rows.length }} / {{ projection.total }} 个，优先选中和有标记的精灵</span></template></p>
    </template>
  </section>
</template>
<style scoped>
/* 块级容器：填满父面板，父面板固定高度时由内部 flex 分配空间，避免圆盘被裁掉。 */
.scene-radar { display: flex; flex-direction: column; height: 100%; min-height: 0; min-width: 0; max-width: 100%; background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius-sm); }
.scene-radar > header, .scene-radar > .radar-legend, .scene-radar > p { flex: none; }
/* 页脚按语义片段整体换行，避免「1 cm」「19 / 20」这类数值被拆到两行。 */
.scene-radar .radar-footnote > span { white-space: nowrap; }
.scene-radar .radar-note { margin-bottom: var(--space-1); }
.scene-radar .radar-debug { color: var(--ink); font-variant-numeric: tabular-nums; }
.scene-radar header { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); min-width: 0; min-height: 44px; padding: 8px var(--space-3); border-bottom: 1px solid var(--line-soft); }
.scene-radar header span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.scene-radar header span, .scene-radar p { min-width: 0; color: var(--muted); font-size: var(--fs-xs); line-height: 1.6; overflow-wrap: anywhere; }
/* svg 外层吃掉剩余高度并居中；svg 自身撑满容器，viewBox 等比缩放保证圆盘完整可见。 */
.radar-body { flex: 1 1 0; min-height: 0; min-width: 0; display: grid; place-items: center; }
.radar-map { pointer-events: none; }
.radar-map image { opacity: .9; }
.scene-radar-scope { display: block; width: 100%; height: 100%; max-width: 100%; max-height: 100%; aspect-ratio: 1; background: var(--surface-1); border-radius: var(--radius-sm); }
.radar-ring, .radar-axis { fill: none; stroke: var(--line); stroke-width: 1; }
.radar-ring { stroke-dasharray: 2 4; }
.radar-axis { stroke-dasharray: 4 5; }
.scene-radar text { fill: var(--muted); font-size: var(--fs-3xs); }
.radar-scale-label { font-size: var(--fs-3xs); font-weight: 600; }
.radar-player-cross { fill: none; stroke: var(--ink); stroke-width: 1.5; stroke-linecap: round; }
.scene-radar .radar-target-label { font-size: var(--fs-3xs); font-weight: 700; fill: var(--ink); pointer-events: none; }
/* 标签底色沿用面板/悬浮层底色：避免标签与点位、网格线粘连。 */
.scene-radar { --radar-label-bg: var(--panel); }
.radar-label-bg { fill: var(--radar-label-bg); fill-opacity: .86; }
.radar-label.selected .radar-label-bg { fill-opacity: .96; }
.radar-legend { display: flex; flex-wrap: wrap; gap: var(--space-3); margin: 8px var(--space-3); color: var(--muted); font-size: var(--fs-2xs); }
.radar-legend span { display: inline-flex; align-items: center; gap: var(--space-1); }
.radar-legend-dot { width: 9px; height: 9px; border-radius: 50%; background: var(--teal); }
.radar-legend-dot.is-marked { background: var(--amber); }
.radar-legend-dot.is-double { width: 11px; height: 11px; background: var(--danger); border: 1px solid var(--danger-ink); }
.radar-player { fill: var(--teal-deep); stroke: var(--panel); stroke-width: 3; }
.radar-player-icon { color: var(--panel); width: 14px; height: 14px; }
.scene-radar .radar-self-label { fill: var(--panel); font-size: var(--fs-3xs); font-weight: 700; paint-order: stroke; stroke: var(--teal-deep); stroke-width: 4; stroke-linejoin: round; }
.radar-target { cursor: pointer; outline: none; }
.radar-label { pointer-events: none; }
.radar-hit { fill: transparent; }
.radar-attention-ring { fill: none; stroke-width: 2.5; }
.radar-target.attention-tone-0 .radar-attention-ring { stroke: var(--radar-attention-0); }
.radar-target.attention-tone-1 .radar-attention-ring { stroke: var(--radar-attention-1); }
.radar-target.attention-tone-2 .radar-attention-ring { stroke: var(--radar-attention-2); }
.radar-target.attention-tone-3 .radar-attention-ring { stroke: var(--radar-attention-3); }
.radar-target.attention-tone-4 .radar-attention-ring { stroke: var(--radar-attention-4); }
.radar-point { fill: var(--teal); stroke: var(--panel); stroke-width: 2; }
.radar-target.is-marked .radar-point { fill: var(--amber); }
.radar-target.is-double .radar-point { fill: var(--danger); stroke: var(--panel); stroke-width: 2.5; }
.radar-target.selected .radar-hit, .radar-target:focus-visible .radar-hit { fill: var(--accent); stroke: var(--teal-dark); stroke-width: 2; }
.radar-label.selected .radar-target-label { font-size: var(--fs-3xs); fill: var(--teal-deep); }
.scene-radar > p { margin: 0; padding: 8px var(--space-3); border-top: 1px solid var(--line-soft); }
.scene-radar.is-overlay { flex: 1; min-height: 0; padding: 0; border: 0; background: transparent; --radar-label-bg: var(--radar-overlay-bg); }
.is-overlay header { display: none; }
.is-overlay .radar-legend { flex: none; margin: 0 0 var(--space-2); justify-content: center; }
.is-overlay .radar-body { margin: 0; align-items: end; }
.is-overlay .scene-radar-scope { width: 100%; height: auto; aspect-ratio: 1; background: transparent; border-radius: 10px; overflow: hidden; }
.is-overlay .radar-point { fill: var(--radar-overlay-point); stroke: var(--radar-overlay-bg); }
.is-overlay .radar-target-label { fill: var(--radar-overlay-ink); }
.is-overlay .radar-label.selected .radar-target-label { fill: var(--radar-overlay-ink); }
.scene-radar.is-overlay .radar-target.is-marked .radar-point { fill: var(--amber-bright); }
.scene-radar.is-overlay .radar-target.is-double .radar-point { fill: var(--danger); stroke: var(--radar-overlay-bg); }
.scene-radar.is-overlay .radar-legend-dot { background: var(--radar-overlay-point); }
.scene-radar.is-overlay .radar-legend-dot.is-marked { background: var(--amber-bright); }
.scene-radar.is-overlay .radar-legend-dot.is-double { background: var(--danger); border-color: var(--danger); }
.is-overlay .radar-player { fill: var(--radar-overlay-ink); stroke: var(--radar-overlay-bg); }
.is-overlay .radar-player-cross { stroke: var(--radar-overlay-ink); }
/* 悬浮雷达紧凑窗只在调试图标开启时多显示一行原始坐标，供游戏内就地记录地标。 */
.is-overlay .radar-debug { margin-top: var(--space-1); text-align: center; color: var(--radar-overlay-ink); }
/* 结构分支的交互态：不改变覆盖层与地图投影，只补充悬停/焦点反馈和小窗文字补偿。 */
.radar-target:hover .radar-hit { fill: color-mix(in srgb, var(--teal) 10%, transparent); }
.radar-target:focus-visible .radar-hit,
.radar-target.selected .radar-hit { fill: color-mix(in srgb, var(--teal) 16%, transparent); stroke: var(--teal); stroke-width: 1.5; }
.is-overlay .radar-ring, .is-overlay .radar-axis { stroke: var(--radar-overlay-line); }
.is-overlay .scene-radar text { fill: var(--radar-overlay-muted); }
.is-overlay .radar-label-bg { fill: var(--radar-overlay-bg); fill-opacity: .85; }
.is-overlay .radar-target:hover .radar-hit { fill: color-mix(in srgb, var(--radar-overlay-point) 16%, transparent); }
.is-overlay .radar-target.selected .radar-hit,
.is-overlay .radar-target:focus-visible .radar-hit { fill: color-mix(in srgb, var(--radar-overlay-point) 22%, transparent); stroke: var(--radar-overlay-point); }
/* SVG 字号会随画布等比缩放；空态提示不受标签底片几何约束，窄窗时适当放大。 */
.is-overlay .scene-radar-scope > text { font-size: 16px; }
@media (max-width: 1200px) {
  .scene-radar:not(.is-overlay) .radar-scale-label { font-size: 13px; }
  .scene-radar:not(.is-overlay) .scene-radar-scope > text { font-size: 15px; }
}
</style>
