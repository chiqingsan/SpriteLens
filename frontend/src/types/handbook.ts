export interface HandbookEvolution { key: string | number; name: string }
export interface HandbookMatchups { weak: string[]; resist: string[]; immune: string[] }
export interface HandbookEgg {
  egg_conf_id: number
  name: string
  species_name: string
  hatch_hours: number
  hatch_label: string
  egg_groups: string[]
  egg_type: string
}
export interface HandbookSpecies {
  key: string
  name: string
  display_name: string
  dex_no: number
  handbook_no: string
  icon_url: string
  types: number[]
  egg_groups: string[]
  gender_ratio: [number, number]
  height_range: [number, number]
  weight_range: [number, number]
  reference_ranges: { height: string; weight: string }
  has_shiny: boolean
  type_names: string[]
  type_colors: string[]
  matchups: HandbookMatchups
  stats: Record<string, number>
  stat_sum: number
  quality: number
  stage: number
  max_energy: number
  evolutions: HandbookEvolution[]
  chain_members: HandbookEvolution[]
  egg: HandbookEgg | null
  description: string
}
export interface Handbook {
  species: HandbookSpecies[]
  total: number
  shown: number
  type_options: string[]
  stage_options: number[]
  egg_group_options: string[]
}
export type HandbookSort = 'dex' | 'name' | 'stats'

// 只校验页面消费的字段；新增后端字段不使旧客户端失效。
function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}
function strings(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(item => typeof item === 'string')
}
function numbers(value: unknown): value is number[] {
  return Array.isArray(value) && value.every(item => typeof item === 'number' && Number.isFinite(item))
}
function pair(value: unknown): value is [number, number] {
  return numbers(value) && value.length === 2
}
function evolution(value: unknown): value is HandbookEvolution {
  return record(value) && (typeof value.key === 'string' || Number.isSafeInteger(value.key))
    && typeof value.name === 'string'
}
function ranges(value: unknown): value is { height: string; weight: string } {
  return record(value) && typeof value.height === 'string' && typeof value.weight === 'string'
}
function matchups(value: unknown): value is HandbookMatchups {
  return record(value) && strings(value.weak) && strings(value.resist) && strings(value.immune)
}
function egg(value: unknown): value is HandbookEgg | null {
  if (value === null || value === undefined) return true
  return record(value) && typeof value.name === 'string' && typeof value.hatch_label === 'string'
    && typeof value.hatch_hours === 'number' && typeof value.egg_type === 'string'
    && strings(value.egg_groups)
}
function isSpecies(value: unknown): value is HandbookSpecies {
  if (!record(value)) return false
  return typeof value.key === 'string' && typeof value.name === 'string'
    && ['display_name', 'handbook_no', 'icon_url', 'description'].every(key => typeof value[key] === 'string')
    && ['dex_no', 'stat_sum', 'quality', 'stage', 'max_energy'].every(
      key => Number.isSafeInteger(value[key]))
    && typeof value.has_shiny === 'boolean'
    && numbers(value.types) && strings(value.egg_groups) && strings(value.type_names)
    && strings(value.type_colors)
    && pair(value.gender_ratio) && pair(value.height_range) && pair(value.weight_range)
    && record(value.stats) && Object.values(value.stats).every(item => typeof item === 'number')
    && ranges(value.reference_ranges) && matchups(value.matchups) && egg(value.egg)
    && Array.isArray(value.evolutions) && value.evolutions.every(evolution)
    && Array.isArray(value.chain_members) && value.chain_members.every(evolution)
}
export function parseHandbook(value: unknown): Handbook {
  if (!record(value) || !Array.isArray(value.species) || !value.species.every(isSpecies)
    || !['total', 'shown'].every(key => Number.isSafeInteger(value[key]))
    || !strings(value.type_options) || !strings(value.egg_group_options)
    || !numbers(value.stage_options)) {
    throw new Error('图鉴数据格式不正确')
  }
  return {
    species: value.species, total: Number(value.total), shown: Number(value.shown),
    type_options: value.type_options, stage_options: value.stage_options,
    egg_group_options: value.egg_group_options,
  }
}
