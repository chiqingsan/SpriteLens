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

function viewBox(wrapper: ReturnType<typeof canvas>) { return (wrapper.get('svg').attributes('viewBox') ?? '').split(' ').map(Number) }
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
  it('方向键不再移动窝位，Enter 仍可选择亲本', async () => {
    const wrapper = canvas()
    await nests(wrapper)[1]!.trigger('keydown', { key: 'ArrowRight' })
    expect(wrapper.emitted('move')).toBeUndefined()
    await nests(wrapper)[3]!.trigger('keydown', { key: 'ArrowLeft' })
    expect(wrapper.emitted('move')).toBeUndefined()
    await nests(wrapper)[1]!.trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('select')).toEqual([['2']])
  })
  it('位于原点的窝位可以继续拖到负坐标', async () => {
    const wrapper = canvas({ plan: null, positions: [nest('1', 0, 0)] })
    const nestElement = nests(wrapper)[0]!.element as SVGElement
    const svg = wrapper.get('svg').element as SVGSVGElement
    Object.defineProperty(nestElement, 'setPointerCapture', { value: () => {} })
    Object.defineProperty(nestElement, 'ownerSVGElement', { value: svg })
    Object.defineProperty(svg, 'getBoundingClientRect', { value: () => ({ left: 0, top: 0, width: 400, height: 400 }) })
    nestElement.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true, clientX: 200, clientY: 200 }))
    nestElement.dispatchEvent(new MouseEvent('pointermove', { bubbles: true, clientX: -10, clientY: -10 }))
    nestElement.dispatchEvent(new MouseEvent('pointerup', { bubbles: true }))
    const move = wrapper.emitted('move')?.[0]
    expect(move?.[0]).toBe('1')
    expect(move?.[1]).toBeLessThan(0)
    expect(move?.[2]).toBeLessThan(0)
  })
  it('窝群始终在画布中间且足够大，不贴左上角（验收项）', () => {
    const [x, y, size] = viewBox(canvas())
    expect(size).toBe(400)
    expect(x! + size! / 2).toBe(160)
    expect(y! + size! / 2).toBe(32)
    // 预览不能太小：窝至少要占画布的 1/7
    expect(64 / size!).toBeGreaterThan(1 / 7)
    // 贴着坐标原点的草稿同样必须居中：不能把 (0,0) 固定成画布左上角
    const corner = viewBox(canvas({ positions: [nest('1', 0, 0), nest('2', 2, 0), nest('3', 0, 2), nest('4', 2, 2)] }))
    expect(corner[0]! + corner[2]! / 2).toBe(64)
    expect(corner[1]! + corner[2]! / 2).toBe(64)
    expect(corner[0]!).toBeLessThan(0)
    expect(corner[1]!).toBeLessThan(0)
  })
  it('少窝时也把预览放大到最小视口，而不是缩在画布一角', () => {
    const [x, y, size] = viewBox(canvas({ positions: [nest('1', 0, 0)] }))
    expect(size).toBe(400)
    expect(x! + size! / 2).toBe(32)
    expect(y! + size! / 2).toBe(32)
  })
  it('格距固定 32px，只有越界草稿才扩大视口', () => {
    const grid = canvas().get('rect.planner-board-grid')
    expect([grid.attributes('x'), grid.attributes('width')]).toEqual(['-40', '400'])
    const legacy = canvas({ positions: [nest('1', 0, 0), nest('2', 40, 0)] })
    expect(viewBox(legacy)[2]).toBeGreaterThan(640)
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
