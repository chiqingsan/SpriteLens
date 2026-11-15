<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import UiIcon from './UiIcon.vue'
import MapCoverage from './MapCoverage.vue'
import { containsRaw, projectRaw, type MapPoint } from '../domain/mapProjection'
import { nearbyAttentionTone, type NearbyAttention, type NearbySnapshot } from '../types/nearby'
import type { WorldMapEntry } from '../types/worldMap'

const props = withDefaults(defineProps<{
  data: NearbySnapshot | null
  map: WorldMapEntry
  selected?: string
  /* 场景/实例变化时重置相机；普通数据刷新不得拉回视角。 */
  sceneKey?: string
  visible?: boolean
}>(), { selected: '', sceneKey: '', visible: true })
const emit = defineEmits<{ select: [id: string] }>()

/** 游戏内炫彩标记（彩虹星）：与雷达点位、悬浮条、列表共用同一份本地素材。 */
const RARITY_COLORFUL = '/static/rarity/colorful-fit.webp'

const MIN_ZOOM = 0.05
/** 底图原始分辨率就到 1 像素 ≈ 1 米；3 倍仍是放大查看，不假装有更多细节。 */
const MAX_ZOOM = 3
const ZOOM_STEP = 1.5
/** 用户要求首次定位直接使用最大比例，避免把附近精灵挤成一团。 */
const DEFAULT_ZOOM = MAX_ZOOM
const FIT_PADDING = 0.98
const DRAG_THRESHOLD = 3
/** 标签只给选中目标、有牌目标与悬停目标，数量上限避免密集场景把底图盖住。 */
const LABEL_LIMIT = 8
/** 标签粗略尺寸用于错行：地图上实体常常挤在同一小片区域。 */
/** 12px text × 1.5 line-height + 4px padding + 2px border. */
const LABEL_HEIGHT = 24
const LABEL_CHAR_WIDTH = 11
const LABEL_PADDING = 10
const LABEL_MARGIN = 4
/**
 * 密集场景渲染预算：地图最多为 MAX_RENDERED_TARGETS 个目标建可交互点位（每个点位 3~4 个 DOM 节点）。
 * 只裁渲染不改数据：左侧列表仍展示完整实体，超限说明见下方图例。
 */
const MAX_RENDERED_TARGETS = 160
/** 点位圆心离视口边缘这么近时仍可能露出半颗，更远才不生成。 */
const MARKER_VIEW_MARGIN = 16

interface MapMarker {
  id: string
  name: string
  kind: NearbyAttention
  /** 游戏内固有炫彩外观（mutation 第 4 位），与奖牌关注级别互不覆盖。 */
  colorful: boolean
  tone: number
  x: number
  y: number
  level: number | null
}
interface MapLabel {
  id: string
  text: string
  left: number
  top: number
  anchor: 'start' | 'end'
  selected: boolean
}

const viewport = ref<HTMLElement | null>(null)
const viewportWidth = ref(0)
const viewportHeight = ref(0)
const scale = ref<number | null>(null)
const center = ref<MapPoint | null>(null)
const follow = ref(true)
/* 一旦用户自己缩放/拖动/看全图，就不再自动套用初始街道比例。 */
const userAdjusted = ref(false)
const imageState = ref<'loading' | 'ready' | 'failed'>('loading')
const imageAttempt = ref(0)
const dragging = ref(false)
/* 悬停/键盘聚焦的普通精灵临时出标签：默认不铺名字，靠交互按需展示。 */
const hoveredId = ref<string | null>(null)
let drag: { pointerId: number; startX: number; startY: number; origin: MapPoint; moved: boolean; capture: Element } | null = null
let dragged = false
/* 拖动期间每个 pointermove 都改相机；用一帧一次合并，避免一次手势触发几十次重排。 */
let pendingCenter: MapPoint | null = null
let pendingFrame = 0

const imageIdentity = computed(() => `${props.map.image.url}#${imageAttempt.value}`)
const fitScale = computed(() => {
  if (!viewportWidth.value || !viewportHeight.value) return 0.2
  return Math.max(MIN_ZOOM, Math.min(viewportWidth.value / props.map.image.width, viewportHeight.value / props.map.image.height) * FIT_PADDING)
})
const zoom = computed(() => scale.value ?? fitScale.value)
const zoomPercent = computed(() => Math.max(1, Math.round(zoom.value * 100)))
const viewCenter = computed<MapPoint>(() => center.value ?? { x: props.map.image.width / 2, y: props.map.image.height / 2 })

function clampScale(value: number) {
  const lower = Math.max(MIN_ZOOM, fitScale.value * 0.9)
  return Math.min(MAX_ZOOM, Math.max(lower, value))
}
function screenOffset(point: MapPoint) {
  return {
    x: viewportWidth.value / 2 + (point.x - viewCenter.value.x) * zoom.value,
    y: viewportHeight.value / 2 + (point.y - viewCenter.value.y) * zoom.value,
  }
}
/** 相机中心限制在底图内：底图比视口小时强制居中，避免拖进空白。 */
function clampCenter(point: MapPoint): MapPoint {
  const halfWidth = viewportWidth.value / 2 / zoom.value
  const halfHeight = viewportHeight.value / 2 / zoom.value
  const width = props.map.image.width, height = props.map.image.height
  return {
    x: width <= halfWidth * 2 ? width / 2 : Math.min(width - halfWidth, Math.max(halfWidth, point.x)),
    y: height <= halfHeight * 2 ? height / 2 : Math.min(height - halfHeight, Math.max(halfHeight, point.y)),
  }
}

/** 跟随只对真实位置生效；移动目标参考同样有位置，但标签会说明它还不是玩家落点。 */
const player = computed(() => {
  const position = props.data?.player_position
  const x = position?.[0] ?? null
  const y = position?.[1] ?? null
  if (x === null || y === null || !containsRaw(props.map.projection, x, y)) return null
  const point = projectRaw(props.map.projection, props.map.image, x, y)
  return point ? { ...point, source: props.data?.position_source ?? null } : null
})
const movingTarget = computed(() => props.data?.position_source === 'client_target')
const referenceLabel = computed(() => {
  if (!player.value) return '等待参考位置'
  if (props.data?.position_source === 'battle_return') return '战前位置可能已过期'
  if (movingTarget.value) return '移动目标参考'
  if (props.data?.position_source === 'client_sample' || props.data?.position_source === 'client_stop') return '客户端位置采样'
  return props.data?.position_source === 'teleport' ? '传送落点参考' : '最近观察参考'
})
const playerTag = computed(() => props.data?.position_source === 'battle_return' ? '战前位置' : (movingTarget.value ? '你的移动目标' : '你的位置'))
/** 覆盖归属校验：只画当前账号、当前地图的足迹；切号/切图残留的旧包不画，也不报错。 */
const visibleCoverage = computed(() => {
  const data = props.data
  const coverage = data?.coverage
  if (!data || !coverage || coverage.uid !== data.uid) return null
  return data.resource_id === null || coverage.map_id === data.resource_id ? coverage : null
})
interface RankedMarker extends MapMarker { distance: number }
const markerView = computed<{ markers: MapMarker[]; total: number }>(() => {
  const width = viewportWidth.value
  const height = viewportHeight.value
  if (!width || !height) return { markers: [], total: 0 }
  const candidates: RankedMarker[] = (props.data?.actors || []).flatMap(actor => {
    const position = actor.position
    const x = position?.[0] ?? null
    const y = position?.[1] ?? null
    if (x === null || y === null || !containsRaw(props.map.projection, x, y)) return []
    const point = projectRaw(props.map.projection, props.map.image, x, y)
    if (!point) return []
    const screen = screenOffset(point)
    // 先按视口裁剪再参与标签错行与预算抽样：3 倍缩放下全量目标大多在屏幕外。
    if (screen.x < -MARKER_VIEW_MARGIN || screen.x > width + MARKER_VIEW_MARGIN
      || screen.y < -MARKER_VIEW_MARGIN || screen.y > height + MARKER_VIEW_MARGIN) return []
    return [{
      id: actor.actor_id,
      name: actor.name,
      kind: actor.attention,
      colorful: actor.colorful === true,
      tone: nearbyAttentionTone(actor.actor_id),
      x: point.x,
      y: point.y,
      level: actor.level,
      distance: Math.hypot(screen.x - width / 2, screen.y - height / 2),
    }]
  })
  if (candidates.length <= MAX_RENDERED_TARGETS) return { markers: candidates, total: candidates.length }
  // 选中项优先，其次非普通关注，再按距视口中心由近到远；保持原始顺序，避免推送时节点跳动。
  const keep = new Set<string>()
  if (candidates.some(marker => marker.id === props.selected)) keep.add(props.selected)
  const ranked = [...candidates].sort((a, b) => (a.kind === 'normal' ? 1 : 0) - (b.kind === 'normal' ? 1 : 0)
    || a.distance - b.distance || a.id.localeCompare(b.id))
  for (const marker of ranked) {
    if (keep.size >= MAX_RENDERED_TARGETS) break
    keep.add(marker.id)
  }
  return { markers: candidates.filter(marker => keep.has(marker.id)), total: candidates.length }
})
const markers = computed<MapMarker[]>(() => markerView.value.markers)
const markerTotal = computed(() => markerView.value.total)
const labels = computed<MapLabel[]>(() => {
  if (imageState.value !== 'ready') return []
  const visibleMarkers = markers.value
  const selected = visibleMarkers.find(marker => marker.id === props.selected)
  const picked = visibleMarkers.filter(marker => marker.kind !== 'normal' && marker.id !== selected?.id).slice(0, LABEL_LIMIT)
  // 悬停标签放在最后，只让它避让现有标签，不挤动已显示的名称。
  const hovered = visibleMarkers.find(marker => marker.id === hoveredId.value && marker.id !== selected?.id)
  const hoverRow = hovered && !picked.includes(hovered) ? [hovered] : []
  const rows = [...(selected ? [selected] : []), ...picked, ...hoverRow].map(marker => {
    const screen = screenOffset(marker)
    const anchor: 'start' | 'end' = screen.x > viewportWidth.value / 2 ? 'end' : 'start'
    return {
      id: marker.id,
      text: marker.name,
      left: marker.x * zoom.value + (anchor === 'start' ? 12 : -12),
      top: marker.y * zoom.value - 8,
      anchor,
      selected: marker.id === props.selected,
    }
  })
  // 选中目标保持原位，其余标签向上错行，避免同一小片区域的标签互相盖住。
  const placed: Array<{ left: number; right: number; top: number; bottom: number }> = []
  const stageLeft = viewportWidth.value / 2 - viewCenter.value.x * zoom.value
  const stageTop = viewportHeight.value / 2 - viewCenter.value.y * zoom.value
  const stageWidth = props.map.image.width * zoom.value
  const stageHeight = props.map.image.height * zoom.value
  const minLeft = Math.max(LABEL_MARGIN, -stageLeft + LABEL_MARGIN)
  const maxLeft = Math.min(stageWidth - LABEL_MARGIN, viewportWidth.value - stageLeft - LABEL_MARGIN)
  const minTop = Math.max(LABEL_MARGIN, -stageTop + LABEL_MARGIN)
  const maxTop = Math.min(stageHeight - LABEL_HEIGHT - LABEL_MARGIN, viewportHeight.value - stageTop - LABEL_HEIGHT - LABEL_MARGIN)
  for (const row of rows) {
    const width = Math.min(row.text.length, 12) * LABEL_CHAR_WIDTH + LABEL_PADDING
    const preferredLeft = row.anchor === 'end' ? row.left - width : row.left
    const visibleMaxLeft = maxLeft - width
    const left = visibleMaxLeft >= minLeft
      ? Math.min(visibleMaxLeft, Math.max(minLeft, preferredLeft))
      : minLeft
    const lowerTop = Math.min(minTop, maxTop)
    const upperTop = Math.max(minTop, maxTop)
    const preferredTop = Math.min(upperTop, Math.max(lowerTop, row.top))
    const candidates = [preferredTop]
    for (let offset = LABEL_HEIGHT; offset <= upperTop - lowerTop; offset += LABEL_HEIGHT) {
      candidates.push(preferredTop - offset, preferredTop + offset)
    }
    candidates.push(lowerTop, upperTop)
    row.top = candidates.find(top => {
      if (top < lowerTop || top > upperTop) return false
      const bottom = top + LABEL_HEIGHT
      return !placed.some(box => left < box.right && left + width > box.left && top < box.bottom && bottom > box.top)
    }) ?? preferredTop
    row.left = row.anchor === 'end' ? left + width : left
    placed.push({ left, right: left + width, top: row.top, bottom: row.top + LABEL_HEIGHT })
  }
  return rows
})
const stageStyle = computed(() => ({
  width: `${props.map.image.width * zoom.value}px`,
  height: `${props.map.image.height * zoom.value}px`,
  left: `${viewportWidth.value / 2 - viewCenter.value.x * zoom.value}px`,
  top: `${viewportHeight.value / 2 - viewCenter.value.y * zoom.value}px`,
}))
const playerStyle = computed(() => {
  const point = player.value
  return point ? { left: `${point.x * zoom.value}px`, top: `${point.y * zoom.value}px` } : undefined
})

function applyFit(preserveCenter: boolean) {
  scale.value = fitScale.value
  if (!preserveCenter) center.value = { x: props.map.image.width / 2, y: props.map.image.height / 2 }
}
function zoomBy(factor: number) {
  userAdjusted.value = true
  const next = clampScale(zoom.value * factor)
  if (next === zoom.value) return
  scale.value = next
  // 缩放不算手动移图：跟随开着就继续以参考位置为中心。
  if (follow.value && player.value) center.value = { x: player.value.x, y: player.value.y }
}
function zoomAt(factor: number, clientX: number, clientY: number) {
  userAdjusted.value = true
  const element = viewport.value
  if (!element) return
  const rect = element.getBoundingClientRect()
  const offsetX = clientX - rect.left - viewportWidth.value / 2
  const offsetY = clientY - rect.top - viewportHeight.value / 2
  const anchorX = viewCenter.value.x + offsetX / zoom.value
  const anchorY = viewCenter.value.y + offsetY / zoom.value
  const next = clampScale(zoom.value * factor)
  if (next === zoom.value) return
  scale.value = next
  // 跟随状态下滚轮只改倍数，仍把参考位置锁在视口中心；否则以鼠标位置为锚点。
  if (follow.value && player.value) {
    center.value = { x: player.value.x, y: player.value.y }
    return
  }
  center.value = clampCenter({ x: anchorX - offsetX / next, y: anchorY - offsetY / next })
}
function onWheel(event: WheelEvent) {
  zoomAt(Math.exp(-event.deltaY * 0.0015), event.clientX, event.clientY)
}
function fitAll() {
  follow.value = false
  userAdjusted.value = true
  hoveredId.value = null
  applyFit(false)
}
function locate() {
  if (!player.value) return
  follow.value = true
  userAdjusted.value = true
  scale.value = MAX_ZOOM
  center.value = { x: player.value.x, y: player.value.y }
}
function toggleFollow() {
  follow.value = !follow.value
  if (follow.value) locate()
}
function retryImage() {
  imageState.value = 'loading'
  imageAttempt.value += 1
}
function onImageLoad() { imageState.value = 'ready' }
function onImageError() { imageState.value = 'failed' }

function queueCenter(point: MapPoint) {
  pendingCenter = point
  if (pendingFrame) return
  pendingFrame = requestAnimationFrame(() => {
    pendingFrame = 0
    const next = pendingCenter
    pendingCenter = null
    if (next) center.value = next
  })
}
function flushCenter() {
  if (pendingFrame) {
    cancelAnimationFrame(pendingFrame)
    pendingFrame = 0
  }
  if (pendingCenter) {
    center.value = pendingCenter
    pendingCenter = null
  }
}

function onPointerDown(event: PointerEvent) {
  if (event.button !== 0) return
  const element = viewport.value
  if (!element) return
  event.preventDefault()
  const capture = (event.target as Element).closest('.scene-map-marker') ?? element
  try { capture.setPointerCapture(event.pointerId) } catch { /* 指针可能已被浏览器释放；拖动不依赖捕获也能结束 */ }
  dragged = false
  dragging.value = true
  drag = { pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, origin: { ...viewCenter.value }, moved: false, capture }
}
function onPointerMove(event: PointerEvent) {
  if (!drag || drag.pointerId !== event.pointerId) return
  const dx = event.clientX - drag.startX
  const dy = event.clientY - drag.startY
  if (!drag.moved && Math.hypot(dx, dy) < DRAG_THRESHOLD) return
  drag.moved = true
  dragged = true
  follow.value = false
  userAdjusted.value = true
  queueCenter(clampCenter({ x: drag.origin.x - dx / zoom.value, y: drag.origin.y - dy / zoom.value }))
}
function endDrag(event: PointerEvent) {
  if (!drag || drag.pointerId !== event.pointerId) return
  try { drag.capture.releasePointerCapture(event.pointerId) } catch { /* 同上 */ }
  flushCenter()
  dragging.value = false
  drag = null
}
function selectMarker(event: MouseEvent, id: string) {
  if (!dragged || event.detail === 0) emit('select', id)
}

let observer: ResizeObserver | null = null
onMounted(() => {
  const element = viewport.value
  if (!element) return
  const measure = () => {
    if (!props.visible || !element.clientWidth || !element.clientHeight) return
    viewportWidth.value = element.clientWidth
    viewportHeight.value = element.clientHeight
  }
  measure()
  observer = new ResizeObserver(measure)
  observer.observe(element)
})
onBeforeUnmount(() => { observer?.disconnect(); observer = null; if (pendingFrame) { cancelAnimationFrame(pendingFrame); pendingFrame = 0 } })

// 隐藏视图的零尺寸不参与相机计算；跟随时由位置 watcher 保持居中。
watch([viewportWidth, viewportHeight], () => {
  if (scale.value === null) applyFit(false)
  else if (!follow.value) center.value = clampCenter(viewCenter.value)
})
watch(() => props.sceneKey, () => {
  imageState.value = 'loading'
  imageAttempt.value += 1
  scale.value = null
  center.value = null
  follow.value = true
  userAdjusted.value = false
  hoveredId.value = null
})
watch(() => props.map.image.url, () => {
  imageState.value = 'loading'
  imageAttempt.value += 1
  scale.value = null
  center.value = null
  follow.value = true
  hoveredId.value = null
})
/* 首次打开、换图后自动定位到参考位置；之后跟随只响应位置变化，不拉回用户已暂停的视角。 */
watch([player, imageState, viewportWidth, viewportHeight, () => props.visible], ([next, state]) => {
  if (!props.visible || !viewportWidth.value || !viewportHeight.value || !follow.value || !next || state !== 'ready') return
  // 第一次定位（用户还没自己操作过相机）直接落到街道级比例，而不是把整张大陆塞进视口。
  if (!userAdjusted.value) scale.value = clampScale(Math.max(fitScale.value, DEFAULT_ZOOM))
  if (center.value && center.value.x === next.x && center.value.y === next.y) return
  // 参考位置在地图边缘时仍居中，不能因底图边界把自身图标裁掉一半。
  center.value = { x: next.x, y: next.y }
}, { immediate: true })
</script>

<template>
  <section class="scene-map" aria-label="场景地图">
    <header class="scene-map-head">
      <strong class="scene-map-title">{{ map.name }}</strong>
      <span class="scene-map-reference" :class="{ 'is-moving': movingTarget }">{{ referenceLabel }}</span>
      <span class="scene-map-zoom" :title="`当前缩放 ${zoomPercent}%；100% 时 1 像素约等于 1 米`">{{ zoomPercent }}%</span>
    </header>
    <div ref="viewport" class="scene-map-viewport" :class="{ 'is-dragging': dragging }" @pointerdown="onPointerDown" @pointermove="onPointerMove" @pointerup="endDrag" @pointercancel="endDrag" @lostpointercapture="endDrag" @wheel.prevent="onWheel">
      <div class="scene-map-stage" :style="stageStyle">
        <img :key="imageIdentity" class="scene-map-image" :src="map.image.url + (imageAttempt ? `?retry=${imageAttempt}` : '')" alt="" draggable="false" decoding="async" @load="onImageLoad" @error="onImageError">
        <svg v-if="imageState === 'ready' && visible" class="scene-map-scan" :viewBox="`0 0 ${map.image.width} ${map.image.height}`" preserveAspectRatio="none" aria-hidden="true"><MapCoverage :coverage="visibleCoverage" :map="map" /></svg>
        <button v-for="marker in markers" :key="marker.id" type="button" class="scene-map-marker" :class="[`is-${marker.kind}`, `attention-tone-${marker.tone}`, { selected: selected === marker.id, colorful: marker.colorful }]" :style="{ left: `${marker.x * zoom}px`, top: `${marker.y * zoom}px` }" :aria-label="`${marker.name}${marker.kind === 'double' ? '，双牌' : marker.kind === 'marked' ? '，单牌' : ''}${marker.colorful ? '，炫彩' : ''}`" :aria-pressed="selected === marker.id" @pointerenter="hoveredId = marker.id" @pointerleave="hoveredId = null" @focus="hoveredId = marker.id" @blur="hoveredId = null" @click.stop="selectMarker($event, marker.id)">
          <span class="scene-map-marker-halo" aria-hidden="true"></span>
          <span class="scene-map-marker-dot" aria-hidden="true"></span>
          <span v-if="marker.kind === 'double'" class="scene-map-marker-ring" aria-hidden="true"></span>
          <span v-if="marker.colorful" class="scene-map-marker-colorful-ring" aria-hidden="true"></span>
          <img v-if="marker.colorful" class="scene-map-marker-colorful-badge" :src="RARITY_COLORFUL" alt="" aria-hidden="true">
        </button>
        <span v-for="label in labels" :key="`label-${label.id}`" class="scene-map-label" :class="{ selected: label.selected }" :style="{ left: `${label.left}px`, top: `${label.top}px`, transform: label.anchor === 'end' ? 'translateX(-100%)' : 'none' }" aria-hidden="true">{{ label.text }}</span>
        <div v-if="player" class="scene-map-player" :class="{ 'is-moving': movingTarget }" :style="playerStyle" aria-hidden="true">
          <span class="scene-map-player-halo"></span>
          <span class="scene-map-player-dot"><UiIcon name="current-location" /></span>
          <span class="scene-map-player-tag">{{ playerTag }}</span>
        </div>
      </div>
      <div class="scene-map-tools" role="group" aria-label="地图操作">
        <button type="button" class="scene-map-button" data-action="zoom-in" title="放大" aria-label="放大" :disabled="zoom >= MAX_ZOOM" @pointerdown.stop @click="zoomBy(ZOOM_STEP)"><UiIcon name="zoom-in" /></button>
        <button type="button" class="scene-map-button" data-action="zoom-out" title="缩小" aria-label="缩小" :disabled="zoom <= clampScale(MIN_ZOOM)" @pointerdown.stop @click="zoomBy(1 / ZOOM_STEP)"><UiIcon name="zoom-out" /></button>
        <button type="button" class="scene-map-button" data-action="fit" title="查看全图" aria-label="查看全图" @pointerdown.stop @click="fitAll"><UiIcon name="arrows-maximize" /></button>
        <button type="button" class="scene-map-button" data-action="locate" title="回到参考位置" aria-label="回到参考位置" :disabled="!player" @pointerdown.stop @click="locate"><UiIcon name="current-location" /></button>
        <button type="button" class="scene-map-button" data-action="follow" :aria-pressed="follow" :aria-label="follow ? '暂停跟随参考位置' : '恢复跟随参考位置'" :title="follow ? '跟随中；拖动或缩放后仍锁定参考位置，点击暂停' : '已暂停跟随；点击恢复'" @pointerdown.stop @click="toggleFollow"><UiIcon name="route" /></button>
      </div>
      <div v-if="imageState === 'ready'" class="scene-map-legend" aria-label="地图图例" title="记录范围依据历史日志估计，不代表服务器保证的下发范围；精灵可能刷新，不能保证格内全部精灵已检查。">
        <div v-if="visibleCoverage" class="scene-map-legend-summary"><span><i class="scene-map-legend-swatch is-scanned"></i>记录范围 <b>{{ visibleCoverage.cells }} 格</b></span><span v-if="visibleCoverage.radius_raw">估计半径 {{ visibleCoverage.map_id === '10003' ? `约 ${visibleCoverage.radius_raw / 100} 米` : `${visibleCoverage.radius_raw.toLocaleString('zh-CN')} 原始单位` }}</span><span v-if="visibleCoverage.updated_at">最近新增 {{ new Date(visibleCoverage.updated_at * 1000).toLocaleString('zh-CN') }}</span></div>
        <div class="scene-map-legend-items"><span><i class="scene-map-legend-swatch is-unscanned"></i>未记录</span><span><i class="scene-map-legend-dot is-normal"></i>普通</span><span><i class="scene-map-legend-dot is-marked"></i>单牌</span><span><i class="scene-map-legend-dot is-double"></i>双牌</span><span><i class="scene-map-legend-dot is-player"></i>{{ movingTarget ? '移动目标' : '当前位置' }}</span><span v-if="markerTotal > markers.length">显示 {{ markers.length }} / {{ markerTotal }} 个，优先选中和有标记的精灵</span></div>
      </div>
      <div v-if="imageState === 'loading'" class="scene-map-state">
        <span class="scene-map-spinner" aria-hidden="true"></span>
        <p>正在加载地图…</p>
      </div>
      <div v-else-if="imageState === 'failed'" class="scene-map-state is-error" role="alert">
        <strong>{{ map.name }}底图加载失败</strong>
        <p>检查网络或资源是否完整后重试。</p>
        <button type="button" class="scene-map-button" @pointerdown.stop @click="retryImage">重新加载</button>
      </div>
      <div v-else-if="!player" class="scene-map-state">
        <strong>等待参考位置</strong>
        <p>采集到本次连接的位置后显示。</p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.scene-map { display: flex; flex-direction: column; height: 100%; min-height: 0; min-width: 0; max-width: 100%; background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); overflow: hidden; box-shadow: var(--shadow-sm); }
.scene-map-head { display: flex; align-items: center; gap: var(--space-2); flex: none; min-height: 44px; min-width: 0; padding: 8px var(--space-3); border-bottom: 1px solid var(--line-soft); background: var(--panel); }
.scene-map-title { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: var(--fs-sm); letter-spacing: .01em; }
.scene-map-reference { min-width: 0; padding: 1px var(--space-2); border-radius: 999px; background: var(--surface-2); color: var(--muted); font-size: var(--fs-2xs); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.scene-map-reference.is-moving { background: color-mix(in srgb, var(--amber) 16%, transparent); color: var(--amber-ink); }
.scene-map-zoom { flex: none; margin-left: auto; white-space: nowrap; color: var(--muted); font-size: var(--fs-2xs); font-variant-numeric: tabular-nums; }
.scene-map-viewport { position: relative; flex: 1; min-height: 180px; overflow: hidden; background: var(--surface-1); cursor: grab; touch-action: none; }
.scene-map-viewport.is-dragging { cursor: grabbing; }
.scene-map-stage { position: absolute; }
.scene-map-image { display: block; width: 100%; height: 100%; object-fit: fill; user-select: none; -webkit-user-drag: none; background: var(--surface-2); }
.scene-map-scan { position: absolute; z-index: 1; inset: 0; width: 100%; height: 100%; pointer-events: none; }

.scene-map-marker { position: absolute; z-index: 2; display: grid; place-items: center; width: 26px; height: 26px; padding: 0; margin: 0; border: 0; background: none; transform: translate(-50%, -50%); cursor: pointer; outline: none; }
.scene-map-marker:not(:disabled):is(:hover, :active) { transform: translate(-50%, -50%); }
.scene-map-button:not(:disabled):is(:hover, :active) { transform: none; }
.scene-map-marker-dot { position: relative; width: 12px; height: 12px; border-radius: 50%; background: var(--teal); border: 2px solid #fff; box-shadow: 0 1px 3px rgb(20 30 20 / 45%); }
.scene-map-marker.is-marked .scene-map-marker-dot { width: 16px; height: 16px; background: var(--amber); }
.scene-map-marker.is-double .scene-map-marker-dot { width: 16px; height: 16px; background: var(--danger); }
.scene-map-marker-ring { position: absolute; inset: 2px; border-radius: 50%; border: 2px solid var(--danger); }
.scene-map-marker.attention-tone-0 .scene-map-marker-ring { border-color: var(--radar-attention-0); }
.scene-map-marker.attention-tone-1 .scene-map-marker-ring { border-color: var(--radar-attention-1); }
.scene-map-marker.attention-tone-2 .scene-map-marker-ring { border-color: var(--radar-attention-2); }
.scene-map-marker.attention-tone-3 .scene-map-marker-ring { border-color: var(--radar-attention-3); }
.scene-map-marker.attention-tone-4 .scene-map-marker-ring { border-color: var(--radar-attention-4); }
/* 炫彩：与雷达点位同一套语言——彩虹渐变描边 + 游戏内星标，与双牌/关注色环可同时出现。 */
.scene-map-marker-colorful-ring { position: absolute; inset: -3px; border-radius: 50%; padding: 2.5px; background: var(--colorful-gradient); -webkit-mask: radial-gradient(farthest-side, transparent calc(100% - 2.5px), #000 calc(100% - 2.5px)); mask: radial-gradient(farthest-side, transparent calc(100% - 2.5px), #000 calc(100% - 2.5px)); }
.scene-map-marker-colorful-badge { position: absolute; right: -2px; bottom: -2px; z-index: 1; width: 13px; height: 13px; object-fit: contain; pointer-events: none; filter: drop-shadow(0 1px 2px rgb(20 30 20 / 55%)); }
.scene-map-marker-halo { position: absolute; width: 26px; height: 26px; border-radius: 50%; background: none; transition: background .12s ease; }
.scene-map-marker:hover .scene-map-marker-halo { background: color-mix(in srgb, var(--ink) 8%, transparent); }
.scene-map-marker.selected .scene-map-marker-halo { background: color-mix(in srgb, var(--teal) 22%, transparent); }
.scene-map-marker.selected .scene-map-marker-dot { box-shadow: 0 0 0 3px color-mix(in srgb, var(--teal) 30%, transparent), 0 1px 3px rgb(20 30 20 / 45%); }
.scene-map-marker:focus-visible .scene-map-marker-halo { background: color-mix(in srgb, var(--teal) 22%, transparent); }
.scene-map-marker.selected { z-index: 3; }

.scene-map-label { position: absolute; z-index: 1; max-width: 12ch; padding: 2px var(--space-2); border-radius: 6px; background: color-mix(in srgb, var(--panel) 96%, transparent); border: 1px solid var(--line); box-shadow: 0 1px 4px rgb(20 30 20 / 25%); color: var(--ink); font-size: var(--fs-2xs); font-weight: 700; line-height: 1.5; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; pointer-events: none; }
.scene-map-label.selected { z-index: 3; border-color: var(--teal); color: var(--teal-deep); }

.scene-map-player { position: absolute; z-index: 4; width: 0; height: 0; pointer-events: none; }
.scene-map-player-halo { position: absolute; left: -8.5px; top: -8.5px; width: 17px; height: 17px; border-radius: 50%; background: color-mix(in srgb, var(--teal) 26%, transparent); border: .5px solid color-mix(in srgb, var(--teal) 55%, transparent); animation: scene-map-pulse 2.4s ease-out infinite; }
.scene-map-player-dot { position: absolute; left: -10px; top: -10px; display: grid; place-items: center; width: 20px; height: 20px; color: var(--panel); border: 1.5px solid var(--panel); border-radius: 50%; background: var(--teal-deep); box-shadow: 0 0 0 1.5px var(--teal), 0 1px 3px rgb(20 30 20 / 55%); }
.scene-map-player-dot :deep(.ui-icon) { width: 13px; height: 13px; }
.scene-map-player-tag { position: absolute; top: 18px; left: 0; transform: translateX(-50%); padding: 3px 8px; border-radius: 5px; background: var(--teal-deep); color: var(--panel); font-size: var(--fs-3xs); font-weight: 700; line-height: 1.5; white-space: nowrap; }
.scene-map-player-tag::before { content: ''; position: absolute; top: -4px; left: 50%; margin-left: -4px; border: 4px solid transparent; border-bottom-color: var(--teal-deep); }
.scene-map-player.is-moving .scene-map-player-dot { box-shadow: 0 0 0 .75px rgb(20 30 20 / 40%), 0 1px 3px rgb(20 30 20 / 55%); }
.scene-map-player.is-moving .scene-map-player-dot { background: var(--amber-ink); }
.scene-map-player.is-moving .scene-map-player-halo { background: color-mix(in srgb, var(--amber) 22%, transparent); border-color: color-mix(in srgb, var(--amber) 55%, transparent); }
.scene-map-player.is-moving .scene-map-player-tag { background: var(--amber-ink); }
@keyframes scene-map-pulse { 0% { transform: scale(.7); opacity: .9; } 70% { transform: scale(1.35); opacity: 0; } 100% { transform: scale(1.35); opacity: 0; } }
@media (prefers-reduced-motion: reduce) { .scene-map-player-halo { animation: none; opacity: .55; } }

.scene-map-tools { position: absolute; z-index: 5; top: var(--space-2); right: var(--space-2); display: flex; flex-direction: column; gap: 4px; padding: 4px; border: 1px solid var(--line); border-radius: 10px; background: color-mix(in srgb, var(--panel) 88%, transparent); backdrop-filter: blur(6px); box-shadow: 0 2px 8px rgb(20 30 20 / 18%); }
.scene-map-button { display: grid; place-items: center; width: 28px; height: 28px; padding: 0; background: transparent; color: var(--ink); border: 0; border-radius: 7px; cursor: pointer; }
.scene-map-button:hover { background: var(--surface-2); }
.scene-map-button:focus-visible { outline: 2px solid var(--focus-ring); outline-offset: 1px; }
.scene-map-button[aria-pressed='true'] { background: var(--accent); color: var(--teal-deep); }
.scene-map-button:disabled { opacity: .4; cursor: default; }
.scene-map-button :deep(.ui-icon) { width: 17px; height: 17px; }

.scene-map-legend { position: absolute; z-index: 5; left: var(--space-2); bottom: var(--space-2); width: fit-content; max-width: calc(100% - 16px); display: grid; gap: 4px; padding: 7px 10px; border: 1px solid var(--line); border-radius: 8px; background: color-mix(in srgb, var(--panel) 92%, transparent); backdrop-filter: blur(6px); color: var(--ink-soft); font-size: var(--fs-2xs); }
.scene-map-legend-summary, .scene-map-legend-items { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 12px; min-width: 0; }
.scene-map-legend-summary { color: var(--muted); }
.scene-map-legend-summary b { color: var(--ink); font-weight: 600; }
.scene-map-legend-summary > span, .scene-map-legend-items > span { display: inline-flex; align-items: center; gap: 4px; }
.scene-map-legend-dot, .scene-map-legend-swatch { flex: none; }
.scene-map-legend-dot { width: 9px; height: 9px; border-radius: 50%; border: 1px solid #fff; background: var(--teal); }
.scene-map-legend-swatch { width: 11px; height: 9px; border-radius: 3px; border: 1px solid var(--line); }
.scene-map-legend-swatch.is-scanned { background: color-mix(in srgb, var(--radar-attention-3) 45%, var(--panel)); border-color: var(--panel); }
.scene-map-legend-swatch.is-unscanned { background: color-mix(in srgb, var(--surface-1) 80%, var(--panel)); }
.scene-map-legend-dot.is-marked { background: var(--amber); }
.scene-map-legend-dot.is-double { background: var(--danger); }
.scene-map-legend-dot.is-player { background: var(--teal-deep); box-shadow: 0 0 0 2px color-mix(in srgb, var(--teal) 30%, transparent); }

.scene-map-state { position: absolute; z-index: 6; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px; margin: 0; padding: var(--space-4); color: var(--muted); font-size: var(--fs-xs); text-align: center; background: color-mix(in srgb, var(--surface-1) 84%, transparent); pointer-events: none; }
.scene-map-state strong { color: var(--ink); font-size: var(--fs-sm); }
.scene-map-state p { margin: 0; }
.scene-map-state .scene-map-button { width: auto; height: auto; margin-top: 4px; padding: 4px var(--space-3); border: 1px solid var(--line); border-radius: 7px; background: var(--surface-2); font-size: var(--fs-xs); pointer-events: auto; }
.scene-map-state.is-error { color: var(--danger-ink); }
.scene-map-spinner { width: 18px; height: 18px; border: 2px solid var(--line); border-top-color: var(--teal); border-radius: 50%; animation: scene-map-spin .8s linear infinite; }
@keyframes scene-map-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .scene-map-spinner { animation-duration: 2.4s; } }
</style>
