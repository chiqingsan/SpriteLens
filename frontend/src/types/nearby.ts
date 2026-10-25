export interface NearbySummary { uid: string; version: number; observation_id: number; phase: string }
export interface NearbyMark { label: string; name: string; source: 'reference' | 'worn' }
export type NearbyAttention = 'normal' | 'marked' | 'double'
export interface NearbyActor {
  position: (number | null)[] | null
  actor_id: string; config_id: number | null; base_id: number | null
  name: string; icon_url: string; type_names: string[]; level: number | null
  height: number | null; weight: number | null; voice: number | null; updated_at: number
  chain_names: string[]
  marks: NearbyMark[]; attention: NearbyAttention
}
export function nearbyAttentionTone(actorId: string): number {
  let hash = 0
  for (const char of actorId) hash = (hash * 31 + char.charCodeAt(0)) >>> 0
  return hash % 5
}
export interface NearbySnapshot extends NearbySummary {
  player_position: (number | null)[] | null; position_source: string | null
  scene_id: number | null; updated_at: number | null; complete: false
  unresolved_updates: number; rejected_actors: number; actors: NearbyActor[]
  radar_radius_raw: number
  type_icons: Record<string, string>
  mapping_available: boolean
}
function record(v: unknown): v is Record<string, unknown> { return !!v && typeof v === 'object' }
function integer(v: unknown): v is number { return Number.isSafeInteger(v) }
function optional(v: unknown): v is number | null { return v === null || integer(v) }
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
const phases = ['awaiting_identity', 'awaiting_scene', 'resumed_stale', 'observing', 'battle_unverified', 'disconnected', 'stopped', 'historical_account']
export function parseNearbySummary(v: unknown): NearbySummary {
  if (!record(v) || typeof v.uid !== 'string' || !/^\d+$/.test(v.uid)
    || !integer(v.version) || (v.observation_id !== undefined && !integer(v.observation_id))
    || typeof v.phase !== 'string' || !phases.includes(v.phase)) throw Error('附近精灵状态格式无效')
  return { uid: v.uid, version: v.version, observation_id: v.observation_id === undefined ? 0 : v.observation_id, phase: v.phase }
}
function parseActor(v: unknown): NearbyActor {
  if (!record(v) || typeof v.actor_id !== 'string' || !/^\d+$/.test(v.actor_id)
    || !position(v.position) || !optional(v.config_id) || !optional(v.base_id) || typeof v.name !== 'string' || typeof v.icon_url !== 'string'
    || !Array.isArray(v.type_names) || !v.type_names.every(t => typeof t === 'string')
    || (v.chain_names !== undefined && (!Array.isArray(v.chain_names) || !v.chain_names.every(name => typeof name === 'string')))
    || !optional(v.level) || !optional(v.height) || !optional(v.weight) || !optional(v.voice)
    || typeof v.updated_at !== 'number' || !Number.isFinite(v.updated_at)) throw Error('附近精灵响应格式无效')
  const list = parseMarks(v.marks)
  return { ...v, chain_names: (v.chain_names ?? []) as string[], marks: list, attention: parseAttention(v.attention) } as NearbyActor
}
export function parseNearby(v: unknown): NearbySnapshot {
  const summary = parseNearbySummary(v)
  if (!record(v) || v.complete !== false || v.source !== 'observed_partial' || !optional(v.scene_id)
    || !position(v.player_position) || !(v.position_source === null || typeof v.position_source === 'string')
    || !(v.updated_at === null || typeof v.updated_at === 'number' && Number.isFinite(v.updated_at))
    || typeof v.mapping_available !== 'boolean'
    || !(v.type_icons === undefined || record(v.type_icons) && Object.values(v.type_icons).every(url => typeof url === 'string'))
    || !integer(v.unresolved_updates) || !integer(v.rejected_actors) || !Array.isArray(v.actors)) throw Error('附近精灵响应格式无效')
  const radius = v.radar_radius_raw
  if (radius !== undefined && !(integer(radius) && radius > 0)) throw Error('附近精灵雷达范围格式无效')
  const actors = v.actors.map(parseActor)
  return { ...summary, scene_id: v.scene_id, updated_at: v.updated_at, complete: false,
    player_position: v.player_position, position_source: v.position_source,
    unresolved_updates: v.unresolved_updates, rejected_actors: v.rejected_actors,
    radar_radius_raw: radius === undefined ? 10000 : radius, type_icons: (v.type_icons ?? {}) as Record<string, string>, mapping_available: v.mapping_available, actors }
}
