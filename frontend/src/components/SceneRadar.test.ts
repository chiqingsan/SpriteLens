import { mount } from '@vue/test-utils'
import { describe, it, expect } from 'vitest'
import SceneRadar from './SceneRadar.vue'
import { parseNearby } from '../types/nearby'
import type { WorldMapEntry } from '../types/worldMap'
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
    expect(wrapper.text()).toContain('2,000 单位')
    await wrapper.get('.radar-target').trigger('click')
    await wrapper.get('.radar-target').trigger('keydown.enter')
    expect(wrapper.emitted('select')).toEqual([['9007199254740993'], ['9007199254740993']])
  })
  it('调试坐标行仅在开关打开且有位置时出现', () => {
    const debugPayload = (extra: Record<string, unknown>) => parseNearby({ ...payload, debug_coordinates: true, ...extra })
    expect(mount(SceneRadar, { props: { data: snapshot() } }).find('.radar-debug').exists()).toBe(false)
    // 只展示二维 x/y：高度 z 不参与地图校准，即使载荷带了也不显示。
    const full = mount(SceneRadar, { props: { data: debugPayload({ player_position: [306000, 408000, 120] }) } })
    expect(full.get('.radar-debug').text()).toBe('原始坐标 x=306000 y=408000')
    expect(mount(SceneRadar, { props: { data: debugPayload({ player_position: null }) } }).find('.radar-debug').exists()).toBe(false)
    // 悬浮雷达（compact）同样显示，方便在游戏内就地记录地标；关闭开关时不显示。
    const compact = mount(SceneRadar, { props: { data: debugPayload({ player_position: [1, 2, 3] }), compact: true } })
    expect(compact.get('.radar-debug').text()).toBe('原始坐标 x=1 y=2')
    expect(mount(SceneRadar, { props: { data: snapshot(), compact: true } }).find('.radar-debug').exists()).toBe(false)
  })
  it('缺玩家位置时等待，不绘制假目标', () => {
    const wrapper = mount(SceneRadar, { props: { data: parseNearby({ ...payload, player_position: null }) } })
    expect(wrapper.text()).toContain('等待玩家位置')
    expect(wrapper.findAll('.radar-target')).toHaveLength(0)
    expect(wrapper.find('.radar-center-label').exists()).toBe(false)
    expect(wrapper.find('.radar-legend').exists()).toBe(false)
    expect(wrapper.get('header').text()).toBe('场景雷达')
  })
  it('按传入半径固定雷达外环，并隐藏显示距离之外的目标', () => {
    const far = actor('4', '远处精灵', [2500, 0, 0])
    const wrapper = mount(SceneRadar, { props: { data: snapshot([payload.actors[0], far]), radius: 2000 } })
    expect(wrapper.findAll('.radar-target')).toHaveLength(1)
    expect(wrapper.text()).toContain('2,000 单位')
  })
  it('缺失半径时默认使用 10,000 单位', () => {
    const edge = actor('5', '外环精灵', [0, 10000, 0], { attention: 'marked' })
    const wrapper = mount(SceneRadar, { props: { data: snapshot([edge]) } })
    expect(wrapper.text()).toContain('10,000 单位')
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
  it('按标记和双牌状态区分雷达目标', () => {
    const double = actor('3', '双牌精灵', [100, 0, 0], { marks: [
      { label: '大', name: '大块头', source: 'reference' },
      { label: '婉', name: '婉转声', source: 'reference' },
    ], attention: 'double' })
    const wrapper = mount(SceneRadar, { props: { data: snapshot([payload.actors[0], double]) } })
    expect(wrapper.find('.radar-target.is-marked').exists()).toBe(true)
    expect(wrapper.find('.radar-target.is-double').exists()).toBe(true)
    expect(wrapper.find('.radar-target.is-double .radar-point').attributes('r')).toBe('7')
    expect(wrapper.get('.radar-legend').text()).toContain('单牌')
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
  it('玩家中心使用独立定位图标', () => {
    const wrapper = mount(SceneRadar, { props: { data: snapshot() } })
    const player = wrapper.get('.radar-player')
    expect(player.classes()).not.toContain('radar-point')
    expect(player.attributes('cx')).toBe('200')
    expect(player.attributes('cy')).toBe('200')
    expect(player.attributes('r')).toBe('8')
    expect(wrapper.find('.radar-player-icon').exists()).toBe(true)
    expect(wrapper.find('.radar-center-label').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('位置参考')
  })
  it('三环刻度按 1 单位 ≈ 1 cm 折算为米制并随半径缩放', () => {
    const wrapper = mount(SceneRadar, { props: { data: snapshot() } })
    expect(wrapper.findAll('.radar-scale-label').map(node => node.text())).toEqual(['100 m', '50 m', '20 m'])
    const small = mount(SceneRadar, { props: { data: snapshot(), radius: 2000 } })
    expect(small.findAll('.radar-scale-label').map(node => node.text())).toEqual(['20 m', '10 m', '4 m'])
    const fallback = mount(SceneRadar, { props: { data: snapshot(), radius: 0 } })
    expect(fallback.findAll('.radar-scale-label').map(node => node.text())).toEqual(['100 m', '50 m', '20 m'])
  })
  it('默认只标注最近 6 个目标，选中目标即使更远也始终显示标签', () => {
    const spread = [
      actor('101', '甲精灵', [4000, 0, 0], { attention: 'marked' }),
      actor('102', '乙精灵', [3800, 3800, 0], { attention: 'marked' }),
      actor('103', '丙精灵', [0, 5500, 0], { attention: 'marked' }),
      actor('104', '丁精灵', [-4200, 4200, 0], { attention: 'marked' }),
      actor('105', '戊精灵', [-6500, 0, 0], { attention: 'marked' }),
      actor('106', '己精灵', [-4600, -4600, 0], { attention: 'marked' }),
      actor('107', '庚精灵', [0, -7000, 0], { attention: 'marked' }),
      actor('108', '辛精灵', [5000, -5000, 0], { attention: 'marked' }),
    ]
    const wrapper = mount(SceneRadar, { props: { data: snapshot(spread) } })
    expect(wrapper.findAll('.radar-target')).toHaveLength(8)
    expect(labelTexts(wrapper)).toEqual(['甲精灵', '乙精灵', '丙精灵', '丁精灵', '戊精灵', '己精灵'])
    const selected = mount(SceneRadar, { props: { data: snapshot(spread), selected: '108' } })
    expect(selected.findAll('.radar-target.selected')).toHaveLength(1)
    expect(labelTexts(selected)).toEqual(['辛精灵', '甲精灵', '乙精灵', '丙精灵', '丁精灵', '戊精灵', '己精灵'])
    expect(selected.get('.radar-label.selected .radar-target-label').text()).toBe('辛精灵')
  })
  it('普通目标不标注名称，单牌/双牌才显示名称；选中普通目标仍显示名称', () => {
    const mixed = [
      actor('401', '普通靠前', [1000, 0, 0]),
      actor('402', '单牌靠后', [6000, 0, 0], { attention: 'marked' }),
    ]
    const wrapper = mount(SceneRadar, { props: { data: snapshot(mixed) } })
    expect(wrapper.findAll('.radar-target')).toHaveLength(2)
    expect(labelTexts(wrapper)).toEqual(['单牌靠后'])
    const selected = mount(SceneRadar, { props: { data: snapshot(mixed), selected: '401' } })
    expect(labelTexts(selected)).toEqual(['普通靠前', '单牌靠后'])
  })
  it('边缘长名称标签翻转方向后仍留在 viewBox 内', () => {
    const edges = [
      actor('201', '极左边缘长名精灵', [-10000, 0, 0], { attention: 'marked' }),
      actor('202', '极右边缘长名精灵', [7000, -7000, 0], { attention: 'marked' }),
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
      actor('301', '吸泥鸥', [1000, 0, 0], { attention: 'marked' }),
      actor('302', '吸泥鸥', [-1000, 0, 0], { attention: 'marked' }),
      actor('303', '吸泥鸥', [0, 1000, 0], { attention: 'marked' }),
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

describe('覆盖格网与渲染预算', () => {
  const MAP: WorldMapEntry = {
    name: '卡洛西亚大陆',
    availability: 'supported',
    image: { url: '/static/maps/10003.webp', width: 4096, height: 4096 },
    projection: { origin_x: 306000, origin_y: 408000, side: 408000 },
    calibration: { level: 'verified' },
  }
  const coverage = {
    uid: '1', map_id: '10003', layer: 'visit', scope: 'session',
    revision: 1, cell_size: 2000, cells: 2, rows: [[210, 160, 2]] as [number, number, number][],
  }
  const withCoverage = (extra: Record<string, unknown> = {}) => parseNearby({
    ...payload, resource_id: '10003', coverage, ...extra,
  })
  it('覆盖格网只生成一份 path，fill/border/mask 复用', () => {
    const wrapper = mount(SceneRadar, { props: { data: withCoverage(), map: MAP } })
    const d = wrapper.get('.map-coverage-fill').attributes('d')
    expect(d).toBeTruthy()
    expect(wrapper.get('.map-coverage-border').attributes('d')).toBe(d)
    expect(wrapper.get('.map-coverage mask path').attributes('d')).toBe(d)
    wrapper.unmount()
  })
  it('visible=false 时不挂载覆盖层，恢复显示后才生成路径', async () => {
    const wrapper = mount(SceneRadar, { props: { data: withCoverage(), map: MAP, visible: false } })
    expect(wrapper.find('.map-coverage').exists()).toBe(false)
    await wrapper.setProps({ visible: true })
    expect(wrapper.get('.map-coverage-fill').attributes('d')).toBeTruthy()
    wrapper.unmount()
  })
  it('uid/map_id 与当前快照不一致时拒绝绘制覆盖', () => {
    const otherMap = mount(SceneRadar, { props: { data: withCoverage({ coverage: { ...coverage, map_id: '10018' } }), map: MAP } })
    expect(otherMap.find('.map-coverage').exists()).toBe(false)
    const otherAccount = mount(SceneRadar, { props: { data: withCoverage({ coverage: { ...coverage, uid: '2' } }), map: MAP } })
    expect(otherAccount.find('.map-coverage').exists()).toBe(false)
    otherMap.unmount(); otherAccount.unmount()
  })
  it('密集场景只渲染最近 160 个目标，选中项仍在且页脚说明', () => {
    const dense = Array.from({ length: 200 }, (_, index) => actor(
      String(500 + index), '精灵' + index, [index * 10, 0, 0],
      index === 42 ? { attention: 'double', marks: [
        { label: '大', name: '大块头', source: 'reference' },
        { label: '婉', name: '婉转声', source: 'reference' },
      ] } : {},
    ))
    const wrapper = mount(SceneRadar, { props: { data: snapshot(dense), selected: '699' } })
    expect(wrapper.findAll('.radar-target')).toHaveLength(160)
    expect(wrapper.findAll('.radar-target.selected')).toHaveLength(1)
    expect(wrapper.text()).toContain('显示 160 / 200 个，优先选中和有标记的精灵')
    wrapper.unmount()
  })
})
