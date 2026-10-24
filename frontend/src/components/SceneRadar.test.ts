import { mount } from '@vue/test-utils'
import { describe, it, expect } from 'vitest'
import SceneRadar from './SceneRadar.vue'
import { parseNearby } from '../types/nearby'
const payload = { uid: '1', version: 1, observation_id: 1, phase: 'observing', complete: false, source: 'observed_partial', mapping_available: true, radar_radius_raw: 10000, scene_id: 1, updated_at: 1, unresolved_updates: 0, rejected_actors: 0, player_position: [0, 0, null], position_source: 'client_target', actors: [
  { actor_id: '9007199254740993', config_id: 1, base_id: null, name: '未知精灵', icon_url: '', type_names: [], level: null, height: null, weight: 0, voice: 0, updated_at: 1, marks: [{ label: '婉', name: '婉转声', source: 'reference' }], attention: 'marked', position: [-300, 400, null] },
  { actor_id: '2', config_id: 1, base_id: null, name: '缺位置精灵', icon_url: '', type_names: [], level: 1, height: 0, weight: 0, voice: null, updated_at: 1, marks: [], attention: 'normal', position: [null, 0, 0] },
] }
const snapshot = (actors: unknown[] = payload.actors) => parseNearby({ ...payload, actors })
const actor = (id: string, name: string, position: (number | null)[], extra: Record<string, unknown> = {}) => ({
  ...payload.actors[1], actor_id: id, name, position, ...extra,
})
const labelTexts = (wrapper: ReturnType<typeof mount>) => wrapper.findAll('.radar-target-label').map(node => node.text())
const labelPositions = (wrapper: ReturnType<typeof mount>) => wrapper.findAll('.radar-target-label').map(node => ({
  x: Number(node.attributes('x')),
  y: Number(node.attributes('y')),
}))
describe('参考坐标雷达', () => {
  it('保留零坐标与负坐标，不把缺坐标放在中心；点击保留字符串实体ID', async () => {
    const wrapper = mount(SceneRadar, { props: { data: snapshot(), radius: 2000 } })
    expect(wrapper.findAll('.radar-target')).toHaveLength(1)
    expect(wrapper.get('.radar-target').attributes('transform')).toBe('translate(173,236)')
    const label = wrapper.get('.radar-target-label')
    expect(label.text()).toBe('未知精灵')
    expect(label.attributes('text-anchor')).toBe('end')
    expect(Number(label.attributes('x'))).toBeLessThan(173)
    expect(label.attributes('y')).toBe('251')
    expect(wrapper.text()).toContain('2,000 原始坐标单位')
    await wrapper.get('.radar-target').trigger('click')
    await wrapper.get('.radar-target').trigger('keydown.enter')
    expect(wrapper.emitted('select')).toEqual([['9007199254740993'], ['9007199254740993']])
  })
  it('缺玩家位置时等待，不绘制假目标', () => {
    const wrapper = mount(SceneRadar, { props: { data: parseNearby({ ...payload, player_position: null }) } })
    expect(wrapper.text()).toContain('等待玩家位置')
    expect(wrapper.findAll('.radar-target')).toHaveLength(0)
    expect(wrapper.find('.radar-center-label').exists()).toBe(false)
  })
  it('按传入半径固定雷达外环，并隐藏显示距离之外的目标', () => {
    const far = actor('4', '远处精灵', [2500, 0, 0])
    const wrapper = mount(SceneRadar, { props: { data: snapshot([payload.actors[0], far]), radius: 2000 } })
    expect(wrapper.findAll('.radar-target')).toHaveLength(1)
    expect(wrapper.text()).toContain('2,000 原始坐标单位')
  })
  it('缺失半径时默认使用 10,000 原始坐标单位', () => {
    const edge = actor('5', '外环精灵', [0, 10000, 0])
    const wrapper = mount(SceneRadar, { props: { data: snapshot([edge]) } })
    expect(wrapper.text()).toContain('10,000 原始坐标单位')
    expect(wrapper.get('.radar-target').attributes('transform')).toBe('translate(200,380)')
    const label = wrapper.get('.radar-target-label')
    expect(label.text()).toBe('外环精灵')
    expect(Number(label.attributes('x'))).toBeGreaterThanOrEqual(0)
    expect(Number(label.attributes('y'))).toBeGreaterThanOrEqual(0)
    expect(Number(label.attributes('y'))).toBeLessThanOrEqual(400)
    const far = actor('6', '更远精灵', [12500, 0, 0])
    const hidden = mount(SceneRadar, { props: { data: snapshot([far]) } })
    expect(hidden.findAll('.radar-target')).toHaveLength(0)
  })
  it('按重点和双牌状态区分雷达目标', () => {
    const double = actor('3', '双牌精灵', [100, 0, 0], { marks: [
      { label: '大', name: '大块头', source: 'reference' },
      { label: '婉', name: '婉转声', source: 'reference' },
    ], attention: 'double' })
    const wrapper = mount(SceneRadar, { props: { data: snapshot([payload.actors[0], double]) } })
    expect(wrapper.find('.radar-target.is-marked').exists()).toBe(true)
    expect(wrapper.find('.radar-target.is-double').exists()).toBe(true)
    expect(wrapper.find('.radar-target.is-double .radar-point').attributes('r')).toBe('7')
    expect(wrapper.get('.radar-legend').text()).toContain('重点')
    expect(wrapper.get('.radar-legend').text()).toContain('双牌')
  })
  it('紧凑雷达只在选中目标时显示名称', () => {
    const wrapper = mount(SceneRadar, { props: { data: snapshot(), compact: true, selected: '9007199254740993' } })
    expect(wrapper.get('.radar-target').classes()).toContain('selected')
    expect(wrapper.get('.radar-target-label').text()).toBe('未知精灵')
    expect(wrapper.findAll('.radar-scale-label')).toHaveLength(0)
    const silent = mount(SceneRadar, { props: { data: snapshot(), compact: true } })
    expect(silent.findAll('.radar-target-label')).toHaveLength(0)
  })
  it('绘制玩家中心点、短十字与「你」标签', () => {
    const wrapper = mount(SceneRadar, { props: { data: snapshot() } })
    const player = wrapper.get('.radar-player')
    expect(player.classes()).not.toContain('radar-point')
    expect(player.attributes('cx')).toBe('200')
    expect(player.attributes('cy')).toBe('200')
    expect(player.attributes('r')).toBe('5')
    expect(wrapper.find('.radar-player-cross').exists()).toBe(true)
    const centerLabel = wrapper.get('.radar-center-label')
    expect(centerLabel.text()).toBe('你')
    expect(centerLabel.attributes('x')).toBe('200')
    expect(centerLabel.attributes('y')).toBe('200')
    expect(centerLabel.attributes('dy')).toBe('14')
    expect(centerLabel.attributes('text-anchor')).toBe('middle')
    expect(wrapper.text()).not.toContain('位置参考')
  })
  it('三环刻度按半径显示为 2k / 5k / 10k 并随半径缩放', () => {
    const wrapper = mount(SceneRadar, { props: { data: snapshot() } })
    expect(wrapper.findAll('.radar-scale-label').map(node => node.text())).toEqual(['10k', '5k', '2k'])
    const small = mount(SceneRadar, { props: { data: snapshot(), radius: 2000 } })
    expect(small.findAll('.radar-scale-label').map(node => node.text())).toEqual(['2k', '1k', '400'])
    const fallback = mount(SceneRadar, { props: { data: snapshot(), radius: 0 } })
    expect(fallback.findAll('.radar-scale-label').map(node => node.text())).toEqual(['10k', '5k', '2k'])
  })
  it('默认只标注最近 6 个目标，选中目标即使更远也始终显示标签', () => {
    const spread = [
      actor('101', '甲精灵', [4000, 0, 0]),
      actor('102', '乙精灵', [3800, 3800, 0]),
      actor('103', '丙精灵', [0, 5500, 0]),
      actor('104', '丁精灵', [-4200, 4200, 0]),
      actor('105', '戊精灵', [-6500, 0, 0]),
      actor('106', '己精灵', [-4600, -4600, 0]),
      actor('107', '庚精灵', [0, -7000, 0]),
      actor('108', '辛精灵', [5000, -5000, 0]),
    ]
    const wrapper = mount(SceneRadar, { props: { data: snapshot(spread) } })
    expect(wrapper.findAll('.radar-target')).toHaveLength(8)
    expect(labelTexts(wrapper)).toEqual(['甲精灵', '乙精灵', '丙精灵', '丁精灵', '戊精灵', '己精灵'])
    const selected = mount(SceneRadar, { props: { data: snapshot(spread), selected: '108' } })
    expect(selected.findAll('.radar-target.selected')).toHaveLength(1)
    expect(labelTexts(selected)).toEqual(['辛精灵', '甲精灵', '乙精灵', '丙精灵', '丁精灵', '戊精灵', '己精灵'])
    expect(selected.get('.radar-label.selected .radar-target-label').text()).toBe('辛精灵')
  })
  it('边缘长名称标签翻转方向后仍留在 viewBox 内', () => {
    const edges = [
      actor('201', '极左边缘长名精灵', [-10000, 0, 0]),
      actor('202', '极右边缘长名精灵', [7000, -7000, 0]),
    ]
    const wrapper = mount(SceneRadar, { props: { data: snapshot(edges) } })
    expect(labelTexts(wrapper)).toHaveLength(2)
    for (const { x, y } of labelPositions(wrapper)) {
      expect(x).toBeGreaterThanOrEqual(0)
      expect(x).toBeLessThanOrEqual(400)
      expect(y).toBeGreaterThanOrEqual(0)
      expect(y).toBeLessThanOrEqual(400)
    }
    for (const rect of wrapper.findAll('.radar-label-bg')) {
      const x = Number(rect.attributes('x'))
      const width = Number(rect.attributes('width'))
      expect(x).toBeGreaterThanOrEqual(0)
      expect(x + width).toBeLessThanOrEqual(400)
    }
    // 左侧目标翻转为向右展开，右侧目标翻转为向左展开。
    const anchors = Object.fromEntries(wrapper.findAll('.radar-target-label').map(node => [node.text(), node.attributes('text-anchor')]))
    expect(anchors['极左边缘长名精灵']).toBe('start')
    expect(anchors['极右边缘长名精灵']).toBe('end')
  })
  it('同名目标聚合为「名称 ×N」标签，选中项单独显示', () => {
    const flock = [
      actor('301', '吸泥鸥', [1000, 0, 0]),
      actor('302', '吸泥鸥', [-1000, 0, 0]),
      actor('303', '吸泥鸥', [0, 1000, 0]),
    ]
    const wrapper = mount(SceneRadar, { props: { data: snapshot(flock) } })
    expect(wrapper.findAll('.radar-target')).toHaveLength(3)
    expect(labelTexts(wrapper)).toEqual(['吸泥鸥 ×3'])
    const selected = mount(SceneRadar, { props: { data: snapshot(flock), selected: '301' } })
    expect(labelTexts(selected)).toEqual(['吸泥鸥', '吸泥鸥 ×2'])
  })
  it('svg 填满雷达区域容器并保持等比完整显示', () => {
    const wrapper = mount(SceneRadar, { props: { data: snapshot() } })
    const body = wrapper.get('.radar-body')
    const svg = body.get('svg.scene-radar-scope')
    expect(svg.attributes('viewBox')).toBe('0 0 400 400')
    expect(svg.attributes('preserveAspectRatio')).toBe('xMidYMid meet')
    expect(wrapper.findAll('.radar-ring')).toHaveLength(3)
    expect(wrapper.get('.radar-body').element.parentElement?.classList.contains('scene-radar')).toBe(true)
  })
  it('标签绘制半透明底色矩形避免与点位粘连', () => {
    const wrapper = mount(SceneRadar, { props: { data: snapshot() } })
    const background = wrapper.get('.radar-label-bg')
    expect(Number(background.attributes('width'))).toBeGreaterThan(30)
    expect(Number(background.attributes('height'))).toBeGreaterThan(10)
    expect(background.attributes('rx')).toBe('3')
    expect(wrapper.get('.radar-label').attributes('aria-hidden')).toBe('true')
  })
})
