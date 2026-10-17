import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import BreedingCanvas from './BreedingCanvas.vue'
import type { BreederParent } from '../types/breederLibrary'
import type { NatureReference, Plan, Placement, TargetReference } from '../types/breedingPlanner'

const parent = (gid: string, name: string, gender: 1 | 2): BreederParent => ({ gid, name, species: '合成', dex_no: 1, gender, nature: '开朗',
  groups: ['动物'], marks: [], voice: null, height_ratio: null, weight_ratio: null, is_shiny: false, is_colorful: false, icon_url: '', location: null })
const nest = (gid: string, x: number, y: number, kind: 'normal' | 'academy' = 'normal', lock: '' | 'participation' | 'position' = ''): Placement =>
  ({ gid, x, y, kind, lock, primary_goal_id: '' })
const nature = (): NatureReference => ({ known: {}, random: null, unknown: null })
const reference = (goalId: string, interference: string[]): TargetReference => ({ goal_id: goalId, kind: 'exact', matching_fathers: 1,
  iterative_fathers: 0, father_count: 1, father_fraction: 1, nature_contribution: null, all_father_nature_contribution: null, interference })
const positions = [nest('1', 0, 0), nest('2', 2, 0), nest('3', 6, 0), nest('4', 8, 0)]
const parents = new Map<string, BreederParent>()
for (const item of [parent('1', '甲', 1), parent('2', '乙', 2), parent('3', '丙', 2), parent('4', '丁', 2)]) parents.set(item.gid, item)
const plan = (): Plan => ({ plan_id: 'plan-1', status: 'ready', issues: [], placements: positions,
  edges: [{ male: '1', female: '2', marks: [], groups: [], nature: nature() }, { male: '1', female: '3', marks: [], groups: [], nature: nature() }],
  mothers: [{ gid: '2', egg_key: 'egg-a', fathers: ['1'], references: [reference('g1', [])], primary_goal_id: 'g1', nature: nature() },
    { gid: '3', egg_key: 'egg-a', fathers: ['1'], references: [reference('g1', ['1'])], primary_goal_id: 'g1', nature: nature() }],
  goals: [{ goal_id: 'g1', covered: true, exact_mothers: 1, mother_count: 1, shared_mothers: 0, ready: true, reason: '' }],
  metrics: { males: 1, females: 3, effective_mothers: 2, unused_slots: 0 }, unused_candidates: [] })

function canvas(options: { plan?: Plan | null; pending?: boolean; positions?: Placement[]; selected?: string } = {}) {
  return mount(BreedingCanvas, { props: { positions: options.positions ?? positions, parents, plan: options.plan === undefined ? plan() : options.plan,
    pending: options.pending ?? false, selected: options.selected ?? '' } })
}
const nests = (wrapper: ReturnType<typeof canvas>) => wrapper.findAll('g.planner-nest')

describe('小窝布局草图', () => {
  it('按方案渲染父本连线，标出干扰连边并淡化无配对窝位', () => {
    const wrapper = canvas()
    const lines = wrapper.findAll('line.planner-edge')
    expect(lines).toHaveLength(2)
    expect(lines.filter(line => line.classes('interference'))).toHaveLength(1)
    expect(nests(wrapper)[0]!.classes()).not.toContain('unrelated')
    expect(nests(wrapper)[3]!.classes()).toContain('unrelated')
  })
  it('说明区报告窝数与连线数，待重评和未生成方案时给出对应说明', () => {
    const caption = canvas().get('.planner-canvas-caption').text()
    expect(caption).toContain('共 4 个小窝（普通 4／学院 0）')
    expect(caption).toContain('2 条父本连线')
    expect(caption).toContain('1 条为干扰连边')
    expect(canvas({ pending: true }).get('.planner-canvas-caption').text()).toContain('正在重新评估')
    expect(canvas({ plan: null }).get('.planner-canvas-caption').text()).toContain('拖动窝位可移到空位')
  })
  it('方向键按 2 格移动，重叠和长按连发都不提交', async () => {
    const wrapper = canvas()
    await nests(wrapper)[1]!.trigger('keydown', { key: 'ArrowRight' })
    expect(wrapper.emitted('move')).toEqual([['2', 4, 0, null]])
    await nests(wrapper)[3]!.trigger('keydown', { key: 'ArrowLeft' })
    expect(wrapper.emitted('move')).toHaveLength(1)
    expect(wrapper.get('.planner-warning').text()).toContain('重叠')
    await nests(wrapper)[1]!.trigger('keydown', { key: 'ArrowRight', repeat: true })
    expect(wrapper.emitted('move')).toHaveLength(1)
  })
  it('锁定位置的窝位不响应方向键，Enter 用于选择亲本', async () => {
    const wrapper = canvas({ positions: [nest('1', 0, 0), nest('2', 2, 0), nest('3', 6, 0), nest('4', 8, 0, 'normal', 'position')] })
    await nests(wrapper)[3]!.trigger('keydown', { key: 'ArrowLeft' })
    expect(wrapper.emitted('move')).toBeUndefined()
    await nests(wrapper)[1]!.trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('select')).toEqual([['2']])
  })
  it('固定显示整块 20×20 棋盘，只有越界草稿才扩大视图', () => {
    expect(canvas().get('svg').attributes('viewBox')).toBe('0 0 640 640')
    expect(canvas().get('rect.planner-board-border').attributes('width')).toBe('640')
    const legacy = canvas({ positions: [nest('1', 0, 0), nest('2', 40, 0)] })
    expect(legacy.get('svg').attributes('viewBox')).not.toBe('0 0 640 640')
    expect(legacy.get('.planner-canvas-outside').text()).toContain('超出 20×20')
  })
  it('待重评时隐藏旧连线，选中亲本后只强调相关连线', () => {
    const pending = canvas({ pending: true })
    expect(pending.findAll('line.planner-edge')).toHaveLength(0)
    expect(pending.find('.planner-canvas-legend').exists()).toBe(false)
    expect(canvas({ selected: '3' }).findAll('line.planner-edge.dim')).toHaveLength(1)
  })
  it('学院窝与锁定窝位用文字角标表达，不靠颜色', () => {
    const badges = canvas({ positions: [nest('1', 0, 0, 'academy'), nest('2', 2, 0, 'normal', 'position')] }).findAll('g.planner-nest-badge')
    expect(badges).toHaveLength(2)
    expect(badges[0]!.text()).toContain('学')
    expect(badges[1]!.text()).toContain('锁')
    expect(badges[1]!.find('title').text()).toContain('位置锁定')
  })
})
