export interface WikiSkill {
  id: string; name: string; description: string; type: string; category: string
  power: number | null; energy: number | null; source: string; level: number | null; blood: string
}
export interface WikiReference {
  source_url: string; updated_at: string; classification: string
  can_ride: boolean | null; can_double_ride: boolean | null
  feature: { name: string; description: string } | null
  skills: WikiSkill[]; areas: string[]
  eggs: { name: string; description: string; sources: string[] }[]
  activities: { name: string; window: string; note: string }[]
  evolutions: { name: string; members: { name: string; level: number | null; condition: string; item: string }[] }[]
}
function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}
function textFields(value: Record<string, unknown>, keys: string[]) {
  return keys.every(key => typeof value[key] === 'string')
}
function texts(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(entry => typeof entry === 'string')
}
function numberOrNull(value: unknown) { return value === null || (typeof value === 'number' && Number.isFinite(value)) }
export function isWikiReference(value: unknown): value is WikiReference | null | undefined {
  if (value === null || value === undefined) return true
  return record(value) && textFields(value, ['source_url', 'updated_at', 'classification'])
    && [value.can_ride, value.can_double_ride].every(entry => entry === null || typeof entry === 'boolean')
    && (value.feature === null || (record(value.feature) && textFields(value.feature, ['name', 'description'])))
    && texts(value.areas) && Array.isArray(value.skills) && value.skills.every(skill =>
      record(skill) && textFields(skill, ['id', 'name', 'description', 'type', 'category', 'source', 'blood'])
      && ['power', 'energy', 'level'].every(key => numberOrNull(skill[key])))
    && Array.isArray(value.eggs) && value.eggs.every(egg => record(egg)
      && textFields(egg, ['name', 'description']) && texts(egg.sources))
    && Array.isArray(value.activities) && value.activities.every(activity => record(activity)
      && textFields(activity, ['name', 'window', 'note']))
    && Array.isArray(value.evolutions) && value.evolutions.every(branch => record(branch)
      && typeof branch.name === 'string' && Array.isArray(branch.members) && branch.members.every(member =>
        record(member) && textFields(member, ['name', 'condition', 'item']) && numberOrNull(member.level)))
}
