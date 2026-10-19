import type { BreederParent } from './breederLibrary'
import { isBreederParent } from './breederLibrary'
export type Mode = 'target' | 'selected'
export interface Goal { goal_id: string; egg_key: string; size_mark: string; voice_mark: string; nature_id: number; priority: number }
export interface Placement { gid: string; x: number; y: number; kind: 'normal' | 'academy'; lock: '' | 'participation' | 'position'; primary_goal_id: string }
export interface Draft {
  mode: Mode; goals: Goal[]; selected: string[]; participation: 'best' | 'all'; capacity: number; academy: boolean
  placements: Placement[]; approved: string[]; rule_version: string; geometry_version: string
}
export interface PlannerContext {
  uid: number; version: number; available: boolean; source: string; pet_count: number; issues: string[]
  parents: Array<BreederParent & { egg_key: string | null }>
  eggs: Array<{ egg_key: string; name: string; groups: string[]; icon_url: string; chain_names?: string[] }>
  natures: Array<{ id: number; name: string }>; rule_version: string; geometry_version: string; catalog_version: string
}
export interface NatureReference { known: Record<string, number>; random: number | null; unknown: number | null }
export interface TargetReference {
  goal_id: string; kind: 'exact' | 'iterative' | 'unknown'; matching_fathers: number; iterative_fathers: number; father_count: number
  father_fraction: number | null; nature_contribution: number | null; all_father_nature_contribution: number | null; interference: string[]
}
export interface Plan {
  plan_id: string; status: string; issues: string[]; placements: Placement[]
  edges: Array<{ male: string; female: string; marks: string[]; groups: string[]; nature: NatureReference }>
  mothers: Array<{ gid: string; egg_key: string | null; fathers: string[]; references: TargetReference[]; primary_goal_id: string; nature: NatureReference }>
  goals: Array<{ goal_id: string; covered: boolean; exact_mothers: number; mother_count: number; shared_mothers: number; ready: boolean; reason: string }>
  metrics: { males?: number; females?: number; effective_mothers?: number; gender_gap?: number; same_chain?: number; academy_nature_matches?: number; unused_slots?: number }
  unused_candidates: Array<{ gid: string; reason: string }>
}
export interface Iteration {
  key: string; goal_id: string; male: string; female: string; kind: string; missing_marks: string[]
  missing_parent: string | null; candidate_voice: number | null; candidate_weight_ratio: number | null
  candidate_weight: number | null; candidate_species: string | null; anchor_voice: number | null
  gap: number | null; approved: boolean; has_exact: boolean | null; evidence: string
}
export interface Result { uid: number; version: number; revision: number; status: string; search_status: string; issues: string[]; plans: Plan[]; iterations: Iteration[] }

function object(value: unknown): value is Record<string, unknown> { return !!value && typeof value === 'object' && !Array.isArray(value) }
function strings(value: unknown): value is string[] { return Array.isArray(value) && value.every(item => typeof item === 'string') }
function finite(value: unknown): value is number { return typeof value === 'number' && Number.isFinite(value) }
function nullable(value: unknown): boolean { return value === null || finite(value) }
function list(value: unknown, check: (item: Record<string, unknown>) => boolean): boolean { return Array.isArray(value) && value.every(item => object(item) && check(item)) }
function position(value: Record<string, unknown>): boolean {
  return typeof value.gid === 'string' && /^[1-9]\d*$/.test(value.gid) && finite(value.x) && finite(value.y)
    && ['normal', 'academy'].includes(String(value.kind)) && ['', 'participation', 'position'].includes(String(value.lock)) && typeof value.primary_goal_id === 'string'
}
function nature(value: unknown): boolean {
  return object(value) && object(value.known) && Object.values(value.known).every(finite)
    && [value.random, value.unknown].every(v => v === null || finite(v))
}
export function parseContext(value: unknown): PlannerContext {
  if (!object(value) || !Number.isSafeInteger(value.uid) || !Number.isSafeInteger(value.version) || typeof value.available !== 'boolean'
    || !strings(value.issues) || !list(value.eggs, e => ['egg_key', 'name', 'icon_url'].every(k => typeof e[k] === 'string') && strings(e.groups))
    || !list(value.natures, n => Number.isSafeInteger(n.id) && typeof n.name === 'string')
    || !list(value.parents, p => isBreederParent(p) && (p.egg_key === null || typeof p.egg_key === 'string'))
    || !Number.isSafeInteger(value.pet_count) || !['observed', 'history'].includes(String(value.source))
    || typeof value.rule_version !== 'string' || typeof value.geometry_version !== 'string' || typeof value.catalog_version !== 'string') throw new Error('规划资料格式错误')
  return value as unknown as PlannerContext
}
export function parseResult(value: unknown): Result {
  if (!object(value) || !Number.isSafeInteger(value.uid) || !Number.isSafeInteger(value.version) || !Number.isSafeInteger(value.revision)
    || !['ready', 'partial', 'no_plan', 'invalid'].includes(String(value.status)) || !strings(value.issues)
    || !['bounded', 'not_run'].includes(String(value.search_status))
    || !list(value.plans, p => typeof p.plan_id === 'string' && ['ready', 'partial', 'no_plan', 'invalid'].includes(String(p.status)) && strings(p.issues) && object(p.metrics) && Object.values(p.metrics).every(finite) && list(p.placements, position)
      && list(p.edges, e => typeof e.male === 'string' && typeof e.female === 'string' && strings(e.marks) && nature(e.nature))
      && list(p.mothers, m => typeof m.gid === 'string' && (m.egg_key === null || typeof m.egg_key === 'string') && typeof m.primary_goal_id === 'string' && strings(m.fathers) && nature(m.nature)
        && list(m.references, r => typeof r.goal_id === 'string' && ['exact', 'iterative', 'unknown'].includes(String(r.kind)) && strings(r.interference)
          && ['matching_fathers', 'iterative_fathers', 'father_count'].every(k => Number.isSafeInteger(r[k])) && ['father_fraction', 'nature_contribution', 'all_father_nature_contribution'].every(k => nullable(r[k]))))
      && list(p.goals, g => typeof g.goal_id === 'string' && typeof g.covered === 'boolean' && typeof g.ready === 'boolean' && typeof g.reason === 'string'
        && ['exact_mothers', 'mother_count', 'shared_mothers'].every(k => Number.isSafeInteger(g[k]))) && list(p.unused_candidates, c => typeof c.gid === 'string' && typeof c.reason === 'string'))
    || !list(value.iterations, i => ['key', 'goal_id', 'male', 'female', 'kind', 'evidence'].every(k => typeof i[k] === 'string') && strings(i.missing_marks)
      && ['iterative', 'unknown'].includes(String(i.kind)) && typeof i.approved === 'boolean' && (i.has_exact === null || typeof i.has_exact === 'boolean')
      && ['candidate_voice', 'candidate_weight_ratio', 'candidate_weight', 'anchor_voice', 'gap'].every(k => nullable(i[k]))
      && (i.candidate_species === null || typeof i.candidate_species === 'string') && (i.missing_parent === null || typeof i.missing_parent === 'string'))) throw new Error('配窝结果格式错误')
  return value as unknown as Result
}
export function parseSaved(value: unknown): Draft {
  if (!object(value) || !['target', 'selected'].includes(String(value.mode)) || !Number.isInteger(value.capacity)
    || Number(value.capacity) < 0 || Number(value.capacity) > 10 || typeof value.academy !== 'boolean' || !['best', 'all'].includes(String(value.participation))
    || !strings(value.selected) || !strings(value.approved) || !list(value.placements, position)
    || !list(value.goals, g => ['goal_id', 'egg_key', 'size_mark', 'voice_mark'].every(k => typeof g[k] === 'string') && Number.isInteger(g.nature_id) && [0, 1].includes(Number(g.priority)))
    || typeof value.rule_version !== 'string' || typeof value.geometry_version !== 'string') throw new Error('已保存草稿格式错误')
  return value as unknown as Draft
}
