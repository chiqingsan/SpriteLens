export interface CollectionParent {
  gid: string
  name: string
  gender: number
  nature: string
  voice: number
  basis: string[]
  marks: Array<{ name: string; source: 'worn' | 'reference' }>
  height_ratio: number | null
  weight_ratio: number | null
  icon_url: string
  location: { box_id: number; slot: number; row: number; column: number } | null
}
export interface CollectionMember {
  base_id: number; name: string; dex_no: number; stage: number; icon_url: string
}
export interface CollectionLine {
  key: string
  members: CollectionMember[]
  groups: string[]
  status: 'collected' | 'missingMale' | 'missing' | 'unknown'
  gaps: string[]
  mothers: CollectionParent[]
  pairs: Array<{ mother_gid: string; father_gids: string[] }>
}
export interface CollectionLines {
  uid: number; version: number; rule_version: string; available: boolean
  source: 'observed' | 'history'; goal: string; natures: string[]; pet_count: number
  totals: { eligible: number; complete: number; collected: number; missingMale: number; missing: number; unknown: number }
  lines: CollectionLine[]; fathers: CollectionParent[]
}
function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}
function strings(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(item => typeof item === 'string')
}
function location(value: unknown): value is CollectionParent['location'] {
  return value === null || (record(value) && ['box_id', 'slot', 'row', 'column'].every(key => Number.isSafeInteger(value[key])))
}
function parent(value: unknown): value is CollectionParent {
  return record(value) && typeof value.gid === 'string' && /^\d+$/.test(value.gid)
    && typeof value.name === 'string' && Number.isSafeInteger(value.gender)
    && typeof value.nature === 'string' && Number.isFinite(value.voice) && strings(value.basis)
    && Array.isArray(value.marks) && value.marks.every(mark => record(mark)
      && typeof mark.name === 'string' && (mark.source === 'worn' || mark.source === 'reference'))
    && (value.height_ratio === null || typeof value.height_ratio === 'number' && Number.isFinite(value.height_ratio))
    && (value.weight_ratio === null || typeof value.weight_ratio === 'number' && Number.isFinite(value.weight_ratio))
    && typeof value.icon_url === 'string' && location(value.location)
}
function member(value: unknown): value is CollectionMember {
  return record(value) && ['base_id', 'dex_no', 'stage'].every(key => Number.isSafeInteger(value[key]))
    && typeof value.name === 'string' && typeof value.icon_url === 'string'
}
function line(value: unknown): value is CollectionLine {
  return record(value) && typeof value.key === 'string' && Array.isArray(value.members) && value.members.every(member)
    && strings(value.groups) && ['collected', 'missingMale', 'missing', 'unknown'].includes(String(value.status))
    && strings(value.gaps) && Array.isArray(value.mothers) && value.mothers.every(parent)
    && Array.isArray(value.pairs) && value.pairs.every(pair => record(pair)
      && typeof pair.mother_gid === 'string' && strings(pair.father_gids))
}
function validPayload(value: unknown): value is CollectionLines {
  return !(!record(value) || !Number.isSafeInteger(value.uid) || !Number.isSafeInteger(value.version)
    || typeof value.rule_version !== 'string' || typeof value.available !== 'boolean'
    || !['observed', 'history'].includes(String(value.source)) || typeof value.goal !== 'string'
    || !strings(value.natures) || !Number.isSafeInteger(value.pet_count) || !record(value.totals)
    || !['eligible', 'complete', 'collected', 'missingMale', 'missing', 'unknown'].every(key =>
      record(value.totals) && Number.isSafeInteger(value.totals[key]))
    || !Array.isArray(value.lines) || !value.lines.every(line)
    || !Array.isArray(value.fathers) || !value.fathers.every(parent))
}
export function parseCollectionLines(value: unknown): CollectionLines {
  if (!validPayload(value)) throw new Error('双牌产线数据格式错误')
  return value
}
