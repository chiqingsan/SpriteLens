<script setup lang="ts">
import { computed } from 'vue'
import { nearbyAttentionTone, type NearbySnapshot } from '../types/nearby'
const props = withDefaults(defineProps<{ data: NearbySnapshot | null; selected?: string; compact?: boolean; radius?: number }>(), {
  radius: 10000,
})
const emit = defineEmits<{ select: [id: string] }>()
function labelFor(name: string, actorId: string, compact: boolean) {
  const value = name.trim() || `精灵 ${actorId.slice(-4)}`
  const maxLength = compact ? 4 : 8
  return value.length > maxLength ? `${value.slice(0, maxLength)}…` : value
}
const projection = computed(() => {
  const center = props.data?.player_position
  if (!center || center[0] == null || center[1] == null) return null
  const rows = (props.data?.actors || []).flatMap(actor => {
    const position = actor.position
    return !position || position[0] == null || position[1] == null ? []
      : [{ actor, kind: actor.attention, dx: position[0] - center[0]!, dy: position[1] - center[1]!, distance: Math.hypot(position[0] - center[0]!, position[1] - center[1]!) }]
  })
  const range = Number.isFinite(props.radius) && props.radius > 0 ? props.radius : 10000
  const radius = 180
  const projected = rows.filter(row => row.distance <= range).map(row => {
    const x = 200 + row.dx / range * radius, y = 200 + row.dy / range * radius
    const left = x < 200
    return {
      ...row,
      x,
      y,
      attentionTone: nearbyAttentionTone(row.actor.actor_id),
      label: labelFor(row.actor.name, row.actor.actor_id, Boolean(props.compact) && props.selected !== row.actor.actor_id),
      labelX: left ? 9 : -9,
      labelY: y < 200 ? -9 : 15,
      labelAnchor: left ? 'start' : 'end',
    }
  })
  const occupied: Array<{ left: number; right: number; top: number; bottom: number }> = []
  const visible = new Set<string>()
  function priority(row: typeof projected[number]) {
    return row.actor.actor_id === props.selected ? 0 : row.kind === 'double' ? 1 : row.kind === 'marked' ? 2 : 3
  }
  for (const row of [...projected].sort((a, b) => priority(a) - priority(b))) {
    const width = Math.max(18, row.label.length * (row.actor.actor_id === props.selected ? 10 : 9))
    const left = row.labelAnchor === 'start' ? row.x + row.labelX : row.x + row.labelX - width
    const top = row.y + row.labelY - 10
    const box = { left, right: left + width, top, bottom: top + 12 }
    if (!occupied.some(other => box.left < other.right && box.right > other.left && box.top < other.bottom && box.bottom > other.top)) {
      visible.add(row.actor.actor_id)
      occupied.push(box)
    }
  }
  return { range, rows: projected.map(row => ({ ...row, showLabel: visible.has(row.actor.actor_id) })) }
})
</script>
<template>
  <section class="scene-radar" :class="{ 'is-overlay': compact }" aria-label="附近精灵雷达">
    <header><strong>场景雷达</strong><span>{{ !projection ? '等待位置参考' : data?.position_source === 'client_target' ? '以移动目标位置为参考' : data?.position_source === 'teleport' ? '以传送落点为参考' : '以已观察位置为参考' }}</span></header>
    <div v-if="!compact" class="radar-legend" aria-label="雷达目标图例"><span><i class="radar-legend-dot" />普通</span><span><i class="radar-legend-dot is-marked" />重点</span><span><i class="radar-legend-dot is-double" />双牌</span></div>
    <svg viewBox="0 0 400 400" class="scene-radar-scope" role="group" aria-label="参考坐标雷达">
      <circle v-for="radius in [60,120,180]" :key="radius" cx="200" cy="200" :r="radius" class="radar-ring" />
      <path d="M20 200H380M200 20V380" class="radar-axis" />
      <g v-if="projection"><circle cx="200" cy="200" r="7" class="radar-player" /><text v-if="!compact" x="212" y="220">位置参考</text>
        <g v-for="row in projection.rows" :key="row.actor.actor_id" class="radar-target" :class="[`is-${row.kind}`, `attention-tone-${row.attentionTone}`, { selected: selected === row.actor.actor_id }]" :transform="`translate(${row.x},${row.y})`" tabindex="0" role="button" :aria-label="`${row.actor.name}${row.kind === 'double' ? '，双牌' : row.kind === 'marked' ? '，重点标识' : ''}`" @click="emit('select', row.actor.actor_id)" @keydown.enter="emit('select', row.actor.actor_id)" @keydown.space.prevent="emit('select', row.actor.actor_id)">
          <title>{{ row.actor.name }} · {{ row.kind === 'double' ? '双牌' : row.kind === 'marked' ? '重点标识' : '普通' }} · Lv.{{ row.actor.level ?? '未知' }}</title><circle r="12" class="radar-hit"/><circle v-if="row.kind !== 'normal'" r="10" class="radar-attention-ring" /><circle :r="row.kind === 'double' ? 7 : row.kind === 'marked' ? 6 : 5" class="radar-point" />
        </g>
        <g v-for="row in projection.rows" :key="`label-${row.actor.actor_id}`" class="radar-label" :class="{ selected: selected === row.actor.actor_id }" :transform="`translate(${row.x},${row.y})`" aria-hidden="true">
          <text v-if="(!compact && row.showLabel) || selected === row.actor.actor_id" class="radar-target-label" :x="row.labelX" :y="row.labelY" :text-anchor="row.labelAnchor">{{ row.label }}</text>
        </g>
      </g>
      <text v-else x="200" y="200" text-anchor="middle">等待玩家位置</text>
    </svg>
    <template v-if="!compact">
      <p v-if="projection">外环 {{ projection.range.toLocaleString('zh-CN') }} 原始坐标单位 · 已定位 {{ projection.rows.length }} / {{ data?.actors.length ?? 0 }}</p>
      <p v-else>进入场景并移动后更新；缺少位置的精灵仍保留在列表。</p>
      <footer>坐标与方位以原始坐标单位显示，仅作参考，尚未校准为米制；只显示本次已观察范围。</footer>
    </template>
  </section>
</template>
<style scoped>
.scene-radar { width: 100%; min-width: 0; max-width: 100%; padding: var(--space-3); background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius-sm); }
.scene-radar header { display: flex; flex-wrap: wrap; justify-content: space-between; gap: var(--space-3); min-width: 0; }
.scene-radar header span, .scene-radar p, .scene-radar footer { min-width: 0; color: var(--muted); font-size: var(--fs-xs); line-height: 1.6; overflow-wrap: anywhere; }
.scene-radar-scope { display: block; width: 100%; min-width: 0; max-width: 100%; max-height: 560px; aspect-ratio: 1; margin: var(--space-2) auto; background: var(--surface-1); border-radius: var(--radius-sm); }
.radar-ring, .radar-axis { fill: none; stroke: var(--line); stroke-width: 1; }
.radar-axis { stroke-dasharray: 4 5; }
.scene-radar text { fill: var(--muted); font-size: 11px; }
.scene-radar .radar-target-label { font-size: 9px; font-weight: 700; fill: var(--ink); paint-order: stroke; stroke: var(--panel); stroke-width: 4px; stroke-linejoin: round; pointer-events: none; }
.radar-legend { display: flex; flex-wrap: wrap; gap: var(--space-3); margin-top: var(--space-3); color: var(--muted); font-size: var(--fs-2xs); }
.radar-legend span { display: inline-flex; align-items: center; gap: var(--space-1); }
.radar-legend-dot { width: 9px; height: 9px; border-radius: 50%; background: var(--teal); }
.radar-legend-dot.is-marked { background: var(--amber); }
.radar-legend-dot.is-double { width: 11px; height: 11px; background: var(--danger); border: 1px solid var(--danger-ink); }
.radar-player { fill: var(--radar-player, var(--teal-dark)); stroke: var(--panel); stroke-width: 2; }
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
.radar-label.selected .radar-target-label { font-size: 10px; fill: var(--teal-deep); }
.scene-radar footer { padding-top: var(--space-3); border-top: 1px solid var(--line-soft); }
.scene-radar.is-overlay { flex: 1; min-height: 0; display: flex; flex-direction: column; padding: 0; border: 0; background: transparent; }
.is-overlay header { display: none; }
.is-overlay .radar-legend { flex: none; margin: 0 0 var(--space-2); justify-content: center; }
.is-overlay .scene-radar-scope { flex: 1; min-width: 0; min-height: 0; aspect-ratio: auto; margin: 0; background: transparent; }
.is-overlay .radar-point { fill: var(--radar-overlay-point); stroke: var(--radar-overlay-bg); }
.is-overlay .radar-target-label { fill: var(--radar-overlay-ink); stroke: var(--radar-overlay-bg); }
.scene-radar.is-overlay .radar-label.selected .radar-target-label { fill: var(--radar-overlay-ink); stroke: var(--radar-overlay-bg); }
.scene-radar.is-overlay .radar-target.is-marked .radar-point { fill: var(--amber-bright); }
.scene-radar.is-overlay .radar-target.is-double .radar-point { fill: var(--danger); stroke: var(--radar-overlay-bg); }
.scene-radar.is-overlay .radar-legend-dot { background: var(--radar-overlay-point); }
.scene-radar.is-overlay .radar-legend-dot.is-marked { background: var(--amber-bright); }
.scene-radar.is-overlay .radar-legend-dot.is-double { background: var(--danger); border-color: var(--danger); }
.is-overlay .radar-player { fill: var(--radar-player, var(--radar-overlay-point)); }
</style>
