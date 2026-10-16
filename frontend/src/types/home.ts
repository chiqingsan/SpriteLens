export type HomeSource = 'unknown' | 'observed' | 'stale' | 'history'

export interface HomeResident {
  actor_id: string
  instance_id: string
  base_conf_id: number
  nest_guid: string
  name: string
  gender: 0 | 1 | 2
  is_shiny: boolean
  is_colorful: boolean
  level: number
  nature_name: string
  voice: number | null
  height_text: string
  weight_text: string
  height_pct: number | null
  weight_pct: number | null
  medals: Array<{ label: string; name: string; source: string }>
  egg_name: string
  egg_icon_url: string
  egg_weight_range: { min: number; max: number } | null
  egg_groups: string[]
  icon_url: string
  species_name: string
}

export interface HomeNest {
  config_id: number
  guid: string
  kind: 'ordinary' | 'academy'
  name: string
  resident_ids: string[]
}

export interface HomeCouple {
  female_actor_id: string
  female_name: string
  female_nature: string | null
  female_is_academy: boolean
  male_actor_ids: string[]
  male_names: string[]
  male_natures: Array<string | null>
  male_is_academy: boolean[]
  voice_predictions: Array<{ father_actor_id: string; father_name: string; voice: number | null }>
  mode: 'ordinary' | 'academy-mother' | 'academy-father'
  pairing_basis: 'scene' | 'nest-range'
  nature_prediction: {
    distribution: Record<string, number>
    random_percent: number
    unknown_percent: number
    assumption: 'equal-father-probability'
  }
}

export interface HomeSceneEgg {
  actor_id: string
  furniture_guid: string
  npc_config_id: number
}

export interface HomeSnapshot {
  available: boolean
  room_level: number
  residents: HomeResident[]
  nests: HomeNest[]
  couples: HomeCouple[]
  inferred_couples: HomeCouple[]
  scene_eggs: HomeSceneEgg[]
  couples_stale: boolean
  uid: number
  version: number
  pending_deltas: number
  complete: null
  source: HomeSource
}

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function integer(value: unknown): value is number {
  return Number.isSafeInteger(value)
}

function finite(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function nest(value: unknown): value is HomeNest {
  return record(value) && integer(value.config_id) && typeof value.guid === 'string'
    && ['ordinary', 'academy'].includes(String(value.kind)) && typeof value.name === 'string'
    && Array.isArray(value.resident_ids) && value.resident_ids.every(id => typeof id === 'string' && /^\d+$/.test(id))
}

function resident(value: unknown): value is HomeResident {
  return record(value) && typeof value.actor_id === 'string' && /^\d+$/.test(value.actor_id)
    && typeof value.instance_id === 'string' && /^\d+$/.test(value.instance_id)
    && integer(value.base_conf_id) && typeof value.nest_guid === 'string'
    && typeof value.name === 'string' && integer(value.gender) && value.gender >= 0 && value.gender <= 2
    && typeof value.is_shiny === 'boolean' && typeof value.is_colorful === 'boolean'
    && integer(value.level) && typeof value.nature_name === 'string'
    && (value.voice === null || integer(value.voice))
    && typeof value.height_text === 'string' && typeof value.weight_text === 'string'
    && (value.height_pct === null || finite(value.height_pct))
    && (value.weight_pct === null || finite(value.weight_pct))
    && Array.isArray(value.medals) && value.medals.every(mark => record(mark)
      && typeof mark.label === 'string' && typeof mark.name === 'string' && typeof mark.source === 'string')
    && typeof value.egg_name === 'string' && typeof value.egg_icon_url === 'string'
    && (value.egg_weight_range === null || record(value.egg_weight_range)
      && integer(value.egg_weight_range.min) && integer(value.egg_weight_range.max))
    && Array.isArray(value.egg_groups) && value.egg_groups.every(group => typeof group === 'string')
    && typeof value.icon_url === 'string'
    && typeof value.species_name === 'string'
}

function couple(value: unknown, basis?: HomeCouple['pairing_basis']): value is HomeCouple {
  if (!record(value) || !record(value.nature_prediction)
    || !record(value.nature_prediction.distribution)) return false
  return typeof value.female_actor_id === 'string' && /^\d+$/.test(value.female_actor_id)
    && typeof value.female_name === 'string'
    && (typeof value.female_nature === 'string' || value.female_nature === null)
    && typeof value.female_is_academy === 'boolean'
    && Array.isArray(value.male_actor_ids) && value.male_actor_ids.every(id => typeof id === 'string' && /^\d+$/.test(id))
    && Array.isArray(value.male_names) && value.male_names.every(name => typeof name === 'string')
    && Array.isArray(value.male_natures) && value.male_natures.every(name => typeof name === 'string' || name === null)
    && Array.isArray(value.male_is_academy) && value.male_is_academy.every(flag => typeof flag === 'boolean')
    && Array.isArray(value.voice_predictions) && value.voice_predictions.every(prediction => record(prediction)
      && typeof prediction.father_actor_id === 'string' && /^\d+$/.test(prediction.father_actor_id)
      && typeof prediction.father_name === 'string' && (prediction.voice === null || integer(prediction.voice)))
    && ['ordinary', 'academy-mother', 'academy-father'].includes(String(value.mode))
    && (basis ? value.pairing_basis === basis : ['scene', 'nest-range'].includes(String(value.pairing_basis)))
    && Object.values(value.nature_prediction.distribution).every(finite)
    && finite(value.nature_prediction.random_percent) && finite(value.nature_prediction.unknown_percent)
    && value.nature_prediction.assumption === 'equal-father-probability'
}

export function parseHome(value: unknown): HomeSnapshot {
  if (!record(value) || typeof value.available !== 'boolean' || !integer(value.room_level)
    || !Array.isArray(value.residents) || !value.residents.every(resident)
    || !Array.isArray(value.nests) || !value.nests.every(nest)
    || !Array.isArray(value.couples) || !value.couples.every(item => couple(item))
    || !Array.isArray(value.inferred_couples) || !value.inferred_couples.every(item => couple(item, 'nest-range'))
    || !Array.isArray(value.scene_eggs) || !value.scene_eggs.every(egg => record(egg)
      && typeof egg.actor_id === 'string' && /^\d+$/.test(egg.actor_id)
      && typeof egg.furniture_guid === 'string' && integer(egg.npc_config_id))
    || typeof value.couples_stale !== 'boolean'
    || !integer(value.uid) || !integer(value.version) || !integer(value.pending_deltas)
    || value.complete !== null
    || !['unknown', 'observed', 'stale', 'history'].includes(String(value.source))) {
    throw new Error('家园载荷格式无效')
  }
  return value as unknown as HomeSnapshot
}
