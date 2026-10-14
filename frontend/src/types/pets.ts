import { parsePetFilterOptions, type PetFilterOptions } from './petFilters'
import { parsePetConditions, type PetConditions } from './petConditions'

export type PetView = 'point' | 'card' | 'table'
export interface PetStat { key: string; label: string; value: number; race: number; ratio: number; race_ratio: number; talent_add: number; effort_add: number }
export interface PetMeasurement { value: number | null; limits: [number, number] | null; ratio: number | null; status: string }
export interface PetMedal { id: number; name: string; icon_url: string }
export interface EvolutionNode { id: number; name: string; dex_no: number; portrait_url: string }
export interface PetDetailData {
  speciality_name: string; acquisition_name: string; types: { name: string; icon_url: string }[]
  measurements: Record<'height' | 'weight' | 'voice', PetMeasurement>
  egg_limits: Record<'height' | 'weight', [number, number] | null>
  evolution: { nodes: EvolutionNode[]; edges: [number, number][] }
  awarded_medals: PetMedal[] | null
}
export interface RangePosition { ratio: number | null; status: string }
export interface ColorCard { card_id: string; name: string; particle_name: string; particle_id: number; base_color: string; mix_color: string }
export interface MedalMark { label: string; name: string; source: string }
export type PetLocation = { team_id: number; slot: number; historical: boolean } | { box_id: number; slot: number; row: number; column: number }
export interface Pet {
  [key: string]: unknown
  gid: number; name: string; level: number; gender: number; nature_name: string
  nature_positive: string | null; nature_negative: string | null; dex_no: number; species_name: string
  talent_rank: number; talent_color: string; type_names: string[]; type_colors: string[]; egg_groups: string[]
  stats: PetStat[]; height_text: string; weight_text: string; voice_text: string
  height_pct: number; weight_pct: number; voice_pct: number
  range_positions: { height: RangePosition; weight: RangePosition }
  skills: { name: string; equipped: boolean }[]
  portrait_url: string; artwork_url: string; icon_url: string; is_shiny: boolean; is_colorful: boolean
  color_card: ColorCard | null; medal_marks: MedalMark[]
  base_conf_id: number; stat_sum: number; species_stat_sum: number; worn_medal_id: number; worn_medal_name: string
  catch_way: number; add_time: number
  detail: PetDetailData
  location: PetLocation | null; reference_ranges: { height: string; weight: string }; egg_ranges: { height: string; weight: string }
}
export interface PetSlot { gid: number | null; state: 'unknown' | 'empty' | 'missing' | 'matched' | 'filtered' }
export interface PetBox {
  box_id: number; name: string; historical: boolean; slots: PetSlot[]; matched: number; occupied: number; unknown: number
}
export interface PetTeam { team_id: number; name: string; historical: boolean; slots: PetSlot[]; matched: number }
export interface PetBackpack {
  boxes: PetBox[]; teams: PetTeam[]; active_team: number; filtering: boolean
  unlocated_total: number; unlocated_shown: number
}
export interface Pets {
  uid: number; version: number; total: number; shown: number; pets: Pet[]; backpack: PetBackpack
  options: PetFilterOptions & { egg_groups: string[] }; filters: Partial<PetConditions>
}
export interface PetAccount { uid: number; version: number; generation: number }

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}
function number(value: unknown): value is number { return typeof value === 'number' && Number.isFinite(value) }
function integer(value: unknown): value is number { return number(value) && Number.isSafeInteger(value) && value >= 0 }
function strings(value: unknown): value is string[] { return Array.isArray(value) && value.every(item => typeof item === 'string') }
function position(value: unknown): value is RangePosition {
  return record(value) && (value.ratio === null || number(value.ratio)) && typeof value.status === 'string'
}
function colorCard(value: unknown): value is ColorCard {
  return record(value) && ['card_id', 'name', 'particle_name', 'base_color', 'mix_color'].every(key => typeof value[key] === 'string') && integer(value.particle_id)
}
function location(value: unknown): value is PetLocation | null {
  if (value === null) return true
  if (!record(value) || !integer(value.slot) || value.slot < 1) return false
  return 'team_id' in value ? integer(value.team_id) && value.team_id > 0 && value.slot <= 6 && typeof value.historical === 'boolean'
    : integer(value.box_id) && value.box_id > 0 && value.slot <= 30 && integer(value.row) && integer(value.column)
}
function ranges(value: unknown): value is { height: string; weight: string } { return record(value) && typeof value.height === 'string' && typeof value.weight === 'string' }
function limits(value: unknown): value is [number, number] | null { return value === null || Array.isArray(value) && value.length === 2 && value.every(number) && value[1] >= value[0] }
function detail(value: unknown): value is PetDetailData {
  if (!record(value) || !record(value.measurements) || !record(value.evolution) || !Array.isArray(value.evolution.nodes)) return false
  const measurements = value.measurements, evolution = value.evolution, nodes = value.evolution.nodes
  if (!nodes.every((node: unknown): node is EvolutionNode => record(node) && integer(node.id) && integer(node.dex_no)
    && typeof node.name === 'string' && typeof node.portrait_url === 'string')) return false
  return record(value) && typeof value.speciality_name === 'string' && typeof value.acquisition_name === 'string'
    && Array.isArray(value.types) && value.types.every(item => record(item) && typeof item.name === 'string' && typeof item.icon_url === 'string')
    && record(value.measurements) && ['height', 'weight', 'voice'].every(key => {
      const item = measurements[key]
      return record(item) && (item.value === null || number(item.value)) && limits(item.limits) && position(item)
    })
    && record(value.egg_limits) && limits(value.egg_limits.height) && limits(value.egg_limits.weight)
    && Array.isArray(evolution.edges) && evolution.edges.every(edge => Array.isArray(edge) && edge.length === 2 && edge.every(integer)
      && edge.every(id => nodes.some(node => node.id === id)))
    && (value.awarded_medals === null || Array.isArray(value.awarded_medals) && value.awarded_medals.every(item => record(item)
      && integer(item.id) && item.id > 0 && typeof item.name === 'string' && typeof item.icon_url === 'string'))
}
function pet(value: unknown): value is Pet {
  return record(value) && integer(value.gid) && value.gid > 0
    && ['name', 'nature_name', 'species_name', 'talent_color', 'height_text', 'weight_text', 'voice_text'].every(key => typeof value[key] === 'string')
    && ['level', 'gender', 'dex_no', 'talent_rank'].every(key => integer(value[key]))
    && ['height_pct', 'weight_pct', 'voice_pct'].every(key => number(value[key]))
    && ['nature_positive', 'nature_negative'].every(key => value[key] === null || typeof value[key] === 'string')
    && strings(value.type_names) && strings(value.type_colors) && strings(value.egg_groups)
    && Array.isArray(value.stats) && value.stats.every(item => record(item)
      && typeof item.key === 'string' && typeof item.label === 'string'
      && ['value', 'race', 'ratio', 'race_ratio', 'talent_add', 'effort_add'].every(key => number(item[key])))
    && record(value.range_positions) && position(value.range_positions.height) && position(value.range_positions.weight)
    && Array.isArray(value.skills) && value.skills.every(item => record(item) && typeof item.name === 'string' && typeof item.equipped === 'boolean')
    && ['portrait_url', 'artwork_url', 'icon_url'].every(key => typeof value[key] === 'string')
    && typeof value.is_shiny === 'boolean' && typeof value.is_colorful === 'boolean'
    && (value.color_card === null || colorCard(value.color_card))
    && Array.isArray(value.medal_marks) && value.medal_marks.every(item => record(item) && ['label', 'name', 'source'].every(key => typeof item[key] === 'string'))
    && ['base_conf_id', 'stat_sum', 'species_stat_sum', 'worn_medal_id', 'catch_way', 'add_time'].every(key => integer(value[key])) && typeof value.worn_medal_name === 'string'
    && detail(value.detail) && location(value.location) && ranges(value.reference_ranges) && ranges(value.egg_ranges)
}
function slot(value: unknown): value is PetSlot {
  return record(value) && (value.gid === null || integer(value.gid))
    && ['unknown', 'empty', 'missing', 'matched', 'filtered'].includes(String(value.state))
    && (value.state !== 'unknown' || value.gid === null) && (value.state !== 'empty' || value.gid === 0)
    && (!['matched', 'missing', 'filtered'].includes(String(value.state)) || integer(value.gid) && value.gid > 0)
}
function box(value: unknown): value is PetBox {
  return record(value) && integer(value.box_id) && value.box_id > 0 && typeof value.name === 'string'
    && typeof value.historical === 'boolean' && integer(value.matched) && integer(value.occupied) && integer(value.unknown)
    && Array.isArray(value.slots) && value.slots.length === 30 && value.slots.every(slot)
}
function team(value: unknown): value is PetTeam {
  return record(value) && integer(value.team_id) && value.team_id > 0 && typeof value.name === 'string'
    && typeof value.historical === 'boolean' && integer(value.matched)
    && Array.isArray(value.slots) && value.slots.length === 6 && value.slots.every(slot)
}
export function parsePets(value: unknown): Pets {
  if (!record(value) || !integer(value.uid) || !integer(value.version) || !integer(value.total) || !integer(value.shown)
    || !Array.isArray(value.pets) || !value.pets.every(pet) || !record(value.filters) || !record(value.options)
    || !strings(value.options.egg_groups) || !record(value.backpack)
    || !Array.isArray(value.backpack.boxes) || !value.backpack.boxes.every(box)
    || !Array.isArray(value.backpack.teams) || !value.backpack.teams.every(team)
    || !integer(value.backpack.active_team) || typeof value.backpack.filtering !== 'boolean'
    || !integer(value.backpack.unlocated_total) || !integer(value.backpack.unlocated_shown)) {
    throw new Error('宠物列表数据格式不正确')
  }
  const gids = new Set(value.pets.map(item => item.gid))
  if (gids.size !== value.pets.length || value.shown !== value.pets.length || value.shown > value.total
    || [...value.backpack.boxes, ...value.backpack.teams].some(item => item.slots.some(entry => entry.state === 'matched' && !gids.has(entry.gid!)))) {
    throw new Error('宠物列表与箱位数据不一致')
  }
  return { uid: value.uid, version: value.version, total: value.total, shown: value.shown, pets: value.pets,
    filters: parsePetConditions(value.filters), options: { ...parsePetFilterOptions(value.options), egg_groups: value.options.egg_groups },
    backpack: { boxes: value.backpack.boxes, teams: value.backpack.teams, active_team: value.backpack.active_team,
      filtering: value.backpack.filtering, unlocated_total: value.backpack.unlocated_total, unlocated_shown: value.backpack.unlocated_shown } }
}
