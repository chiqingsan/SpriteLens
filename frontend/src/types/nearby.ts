export interface NearbySummary { uid: string; version: number; observation_id: number; phase: string; coverage_error?: string | null }
export interface NearbyMark { label: string; name: string; source: 'reference' | 'worn' }
export type NearbyAttention = 'normal' | 'marked' | 'double'
export interface NearbyActor {
  position: (number | null)[] | null
  stale?: boolean
  actor_id: string; config_id: number | null; base_id: number | null
  name: string; icon_url: string; type_names: string[]; level: number | null
  height: number | null; weight: number | null; voice: number | null; updated_at: number
  /** 参考范围比例（0..1）：身高/体重来自物种范围，声音用家园页同口径；旧包缺失按未知处理。 */
  height_pct?: number | null; weight_pct?: number | null; voice_pct?: number | null
  chain_names: string[]
  /** 场景帧原始外观字段，旧壳层/旧缓存可能没有；mutation 第 4 位即炫彩。 */
  mutation?: number | null; glass_type?: number | null; glass_value?: number | null
  /** 游戏内固有炫彩外观（与背包 is_colorful 同口径），独立于 attention 的奖牌潜力。 */
  colorful?: boolean
  marks: NearbyMark[]; attention: NearbyAttention
}
export function nearbyAttentionTone(actorId: string): number {
  let hash = 0
  for (const char of actorId) hash = (hash * 31 + char.charCodeAt(0)) >>> 0
  return hash % 5
}
/**
 * 本次足迹格网：人物采样及其观察半径覆盖到的格，rows 的每个 run 是同一行内连续的格
 * [gy, gx_start, run_len]，已由后端合并。
 * 格是「人物位置采样所在的世界格」，只表示本次连接取得过位置样本，不是服务器 AOI，也不是探索率证据。
 */
export interface NearbyCoverage {
  uid: string
  map_id: string
  /** 这桶覆盖所属的世界所有者；'0' 是自己的世界，其他 uid 是正在访问的他人世界。 */
  owner: string
  layer: 'visit'
  scope: 'session' | 'history'
  revision: number
  cell_size: number
  cells: number
  rows: [number, number, number][]
  updated_at?: number | null
  radius_raw?: number
}
export interface NearbySnapshot extends NearbySummary {
  coverage_paused?: boolean
  coverage_error?: string | null
  /** 缺失字段按 null 处理：没有有效覆盖时后端下发 null，前端不得用旧包填充。 */
  coverage?: NearbyCoverage | null
  player_position: (number | null)[] | null; position_source: string | null
  /** 主控朝向：0.1° 整数，0° 指 +x、顺时针为正；null 表示尚无朝向样本。 */
  player_heading: number | null
  debug_coordinates: boolean
  resource_id: string | null; instance_id: string | null
  scene_id: number | null; updated_at: number | null; complete: false
  unresolved_updates: number; rejected_actors: number; actors: NearbyActor[]
  radar_radius_raw: number
  type_icons: Record<string, string>
  mapping_available: boolean
}
function record(v: unknown): v is Record<string, unknown> { return !!v && typeof v === 'object' }
function integer(v: unknown): v is number { return Number.isSafeInteger(v) }
function optional(v: unknown): v is number | null { return v === null || integer(v) }
/** 参考范围比例只接受 0..1 的有限数；null/缺省表示未知（旧包与无物种范围的精灵）。 */
function optionalRatio(v: unknown): v is number | null { return v === null || typeof v === 'number' && Number.isFinite(v) }
// 64 位实例号按字符串下发；旧壳层/旧测试缺字段时按 null 处理，不阻断附近观察。
function optionalId(v: unknown): v is string | null | undefined { return v === undefined || v === null || typeof v === 'string' && /^\d+$/.test(v) }
function position(v: unknown): v is (number | null)[] | null { return v === null || Array.isArray(v) && v.length === 3 && v.every(optional) }
function marks(v: unknown): v is NearbyMark[] {
  return Array.isArray(v) && v.every(item => record(item) && typeof item.label === 'string' && typeof item.name === 'string'
    && (item.source === 'reference' || item.source === 'worn'))
}
function parseMarks(v: unknown): NearbyMark[] {
  if (!marks(v)) throw Error('附近精灵标识格式无效')
  return v
}
function parseAttention(v: unknown): NearbyAttention {
  if (v !== 'normal' && v !== 'marked' && v !== 'double') throw Error('附近精灵关注级别无效')
  return v
}
/** 炫彩：变异类型第 4 位（背包 is_colorful 同口径）；后端已算好 colorful，旧包按 mutation 兜底。 */
function colorfulOf(v: Record<string, unknown>): boolean {
  if (typeof v.colorful === 'boolean') return v.colorful
  return typeof v.mutation === 'number' && Number.isSafeInteger(v.mutation) && (v.mutation & 8) !== 0
}
const phases = ['awaiting_identity', 'awaiting_scene', 'resumed_stale', 'observing', 'battle_unverified', 'disconnected', 'stopped', 'historical_account']
export function parseNearbySummary(v: unknown): NearbySummary {
  if (!record(v) || typeof v.uid !== 'string' || !/^\d+$/.test(v.uid)
    || !integer(v.version) || (v.observation_id !== undefined && !integer(v.observation_id))
    || typeof v.phase !== 'string' || !phases.includes(v.phase)
    || (v.coverage_error !== undefined && v.coverage_error !== null && typeof v.coverage_error !== 'string')) throw Error('附近精灵状态格式无效')
  return { uid: v.uid, version: v.version, observation_id: v.observation_id === undefined ? 0 : v.observation_id, phase: v.phase, coverage_error: v.coverage_error ?? null }
}
function parseActor(v: unknown): NearbyActor {
  if (!record(v) || typeof v.actor_id !== 'string' || !/^\d+$/.test(v.actor_id)
    || !position(v.position) || !optional(v.config_id) || !optional(v.base_id) || typeof v.name !== 'string' || typeof v.icon_url !== 'string'
    || !Array.isArray(v.type_names) || !v.type_names.every(t => typeof t === 'string')
    || (v.chain_names !== undefined && (!Array.isArray(v.chain_names) || !v.chain_names.every(name => typeof name === 'string')))
    || !optional(v.level) || !optional(v.height) || !optional(v.weight) || !optional(v.voice)
    || (v.height_pct !== undefined && !optionalRatio(v.height_pct)) || (v.weight_pct !== undefined && !optionalRatio(v.weight_pct))
    || (v.voice_pct !== undefined && !optionalRatio(v.voice_pct))
    || (v.stale !== undefined && typeof v.stale !== 'boolean')
    || (v.mutation !== undefined && !optional(v.mutation)) || (v.glass_type !== undefined && !optional(v.glass_type))
    || (v.glass_value !== undefined && !optional(v.glass_value)) || (v.colorful !== undefined && typeof v.colorful !== 'boolean')
    || typeof v.updated_at !== 'number' || !Number.isFinite(v.updated_at)) throw Error('附近精灵响应格式无效')
  const list = parseMarks(v.marks)
  // 只在为真时补字段：普通精灵保持原样，避免给旧缓存/测试夹具凭空加键。
  return {
    ...v, chain_names: (v.chain_names ?? []) as string[], marks: list, attention: parseAttention(v.attention),
    ...(colorfulOf(v) ? { colorful: true } : {}),
  } as NearbyActor
}
/** 严格校验覆盖格网 DTO：非法整包抛错（load 失败会保留同周期数据），不静默丢字段。 */
function parseCoverage(v: unknown): NearbyCoverage | null {
  if (v === undefined || v === null) return null
  if (!record(v) || typeof v.uid !== 'string' || !/^\d+$/.test(v.uid)
    || typeof v.map_id !== 'string' || !/^\d+$/.test(v.map_id)
    || v.layer !== 'visit' || (v.scope !== 'session' && v.scope !== 'history')
    || !integer(v.revision) || v.revision <= 0
    || !integer(v.cell_size) || v.cell_size <= 0
    || !integer(v.cells) || v.cells <= 0
    || (v.updated_at !== undefined && v.updated_at !== null && (typeof v.updated_at !== 'number' || !Number.isFinite(v.updated_at)))
    || (v.radius_raw !== undefined && (!integer(v.radius_raw) || v.radius_raw < 0))
    // run 数上限对齐后端 MAX_CELLS：散点格最坏情况下每个格独占一个 run。
    || !Array.isArray(v.rows) || v.rows.length > 65536) throw Error('地图观察区域格式无效')
  const rows: [number, number, number][] = []
  let cells = 0
  for (const row of v.rows) {
    if (!Array.isArray(row) || row.length !== 3 || !row.every(integer) || (row[2] as number) <= 0) throw Error('地图观察区域格式无效')
    cells += row[2] as number
    if (!Number.isSafeInteger(cells)) throw Error('地图观察区域格式无效')
    rows.push([row[0] as number, row[1] as number, row[2] as number])
  }
  if (cells !== v.cells) throw Error('地图观察区域格式无效')
  // 旧壳层没有 owner 字段时按自己的世界处理，不阻断附近观察。
  const owner = typeof v.owner === 'string' && /^\d+$/.test(v.owner) ? v.owner : '0'
  return { uid: v.uid, map_id: v.map_id, owner, layer: 'visit', scope: v.scope, revision: v.revision, cell_size: v.cell_size, cells: v.cells, rows, updated_at: v.updated_at === undefined ? null : v.updated_at as number | null, radius_raw: v.radius_raw === undefined ? 0 : v.radius_raw as number }
}
export function parseNearby(v: unknown): NearbySnapshot {
  const summary = parseNearbySummary(v)
  if (!record(v) || v.complete !== false || v.source !== 'observed_partial' || !optional(v.scene_id)
    || !position(v.player_position) || !(v.position_source === null || typeof v.position_source === 'string')
    || !(v.player_heading === undefined || optional(v.player_heading))
    || !(v.debug_coordinates === undefined || typeof v.debug_coordinates === 'boolean')
    || !optionalId(v.resource_id) || !optionalId(v.instance_id)
    || !(v.updated_at === null || typeof v.updated_at === 'number' && Number.isFinite(v.updated_at))
    || typeof v.mapping_available !== 'boolean'
    || !(v.type_icons === undefined || record(v.type_icons) && Object.values(v.type_icons).every(url => typeof url === 'string'))
    || (v.coverage_paused !== undefined && typeof v.coverage_paused !== 'boolean')
    || (v.coverage_error !== undefined && v.coverage_error !== null && typeof v.coverage_error !== 'string')
    || !integer(v.unresolved_updates) || !integer(v.rejected_actors) || !Array.isArray(v.actors)) throw Error('附近精灵响应格式无效')
  const radius = v.radar_radius_raw
  if (radius !== undefined && !(integer(radius) && radius > 0)) throw Error('附近精灵雷达范围格式无效')
  const actors = v.actors.map(parseActor)
  return { ...summary, scene_id: v.scene_id, updated_at: v.updated_at, complete: false,
    coverage: parseCoverage(v.coverage), coverage_paused: v.coverage_paused === true, coverage_error: v.coverage_error ?? null,
    player_position: v.player_position, position_source: v.position_source, debug_coordinates: v.debug_coordinates === true,
    player_heading: typeof v.player_heading === 'number' ? v.player_heading : null,
    resource_id: typeof v.resource_id === 'string' ? v.resource_id : null,
    instance_id: typeof v.instance_id === 'string' ? v.instance_id : null,
    unresolved_updates: v.unresolved_updates, rejected_actors: v.rejected_actors,
    radar_radius_raw: radius === undefined ? 10000 : radius, type_icons: (v.type_icons ?? {}) as Record<string, string>, mapping_available: v.mapping_available, actors }
}
