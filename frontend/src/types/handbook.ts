export interface HandbookEvolution { key: string | number; name: string; dex_no?: number }
export interface HandbookSpecies {
  key: string
  name: string
  display_name: string
  dex_no: number
  handbook_no: string
  icon_url: string
  egg_groups: string[]
  gender_ratio: [number, number]
  height_range: [number, number]
  weight_range: [number, number]
  reference_ranges: { height: string; weight: string }
  has_shiny: boolean
  type_names: string[]
  type_colors: string[]
  stats: Record<string, number>
  stat_sum: number
  quality: number
  stage: number
  max_energy: number
  evolutions: HandbookEvolution[]
  chain_members: HandbookEvolution[]
  collected: boolean
  owned_count: number
  best_level: number
  description: string
}
export interface Handbook {
  species: HandbookSpecies[]
  total: number
  collected: number
  shown: number
  type_options: string[]
}

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
function isSpecies(value: unknown): value is HandbookSpecies {
  if (!record(value)) return false
  return typeof value.key === 'string' && typeof value.name === 'string'
    && ['display_name', 'handbook_no', 'icon_url', 'description'].every(key => typeof value[key] === 'string')
    && ['dex_no', 'stat_sum', 'quality', 'stage', 'max_energy', 'owned_count', 'best_level'].every(
      key => Number.isSafeInteger(value[key]))
    && ['collected', 'has_shiny'].every(key => typeof value[key] === 'boolean')
    && strings(value.egg_groups) && strings(value.type_names) && strings(value.type_colors)
    && pair(value.gender_ratio) && pair(value.height_range) && pair(value.weight_range)
    && record(value.stats) && Object.values(value.stats).every(item => typeof item === 'number')
    && ranges(value.reference_ranges)
    && Array.isArray(value.evolutions) && value.evolutions.every(evolution)
    && Array.isArray(value.chain_members) && value.chain_members.every(evolution)
}
export function parseHandbook(value: unknown): Handbook {
  if (!record(value) || !Array.isArray(value.species) || !value.species.every(isSpecies)
    || !['total', 'collected', 'shown'].every(key => Number.isSafeInteger(value[key]))
    || !strings(value.type_options)) {
    throw new Error('图鉴数据格式不正确')
  }
  return {
    species: value.species, total: Number(value.total), collected: Number(value.collected),
    shown: Number(value.shown), type_options: value.type_options,
  }
}
