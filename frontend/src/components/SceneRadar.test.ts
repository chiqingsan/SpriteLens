import { mount } from '@vue/test-utils'
import { describe, it, expect } from 'vitest'
import SceneRadar from './SceneRadar.vue'
import { parseNearby } from '../types/nearby'
const payload = { uid: '1', version: 1, observation_id: 1, phase: 'observing', complete: false, source: 'observed_partial', mapping_available: true, radar_radius_raw: 10000, scene_id: 1, updated_at: 1, unresolved_updates: 0, rejected_actors: 0, player_position: [0, 0, null], position_source: 'client_target', actors: [
  { actor_id: '9007199254740993', config_id: 1, base_id: null, name: '未知精灵', icon_url: '', type_names: [], level: null, height: null, weight: 0, voice: 0, updated_at: 1, marks: [{ label: '婉', name: '婉转声', source: 'reference' }], attention: 'marked', position: [-300, 400, null] },
  { actor_id: '2', config_id: 1, base_id: null, name: '缺位置精灵', icon_url: '', type_names: [], level: 1, height: 0, weight: 0, voice: null, updated_at: 1, marks: [], attention: 'normal', position: [null, 0, 0] },
] }
describe('参考坐标雷达', () => {
  it('保留零坐标与负坐标，不把缺坐标放在中心；点击保留字符串实体ID', async () => {
    const wrapper = mount(SceneRadar, { props: { data: parseNearby(payload), radius: 2000 } })
    expect(wrapper.findAll('.radar-target')).toHaveLength(1)
    expect(wrapper.get('.radar-target').attributes('transform')).toBe('translate(173,236)')
    expect(wrapper.get('.radar-target-label').text()).toBe('未知精灵')
    expect(wrapper.get('.radar-target-label').attributes('x')).toBe('9')
    expect(wrapper.get('.radar-target-label').attributes('y')).toBe('15')
    expect(wrapper.text()).toContain('2,000 原始坐标单位')
    await wrapper.get('.radar-target').trigger('click')
    expect(wrapper.emitted('select')).toEqual([['9007199254740993']])
  })
  it('缺玩家位置时等待，不绘制假目标', () => {
    const wrapper = mount(SceneRadar, { props: { data: parseNearby({ ...payload, player_position: null }) } })
    expect(wrapper.text()).toContain('等待玩家位置')
    expect(wrapper.findAll('.radar-target')).toHaveLength(0)
  })
  it('按传入半径固定雷达外环，并隐藏显示距离之外的目标', () => {
    const far = { ...payload.actors[1], actor_id: '4', name: '远处精灵', position: [2500, 0, 0] }
    const wrapper = mount(SceneRadar, { props: { data: parseNearby({ ...payload, actors: [payload.actors[0], far] }), radius: 2000 } })
    expect(wrapper.findAll('.radar-target')).toHaveLength(1)
    expect(wrapper.text()).toContain('2,000 原始坐标单位')
  })
  it('缺失半径时默认使用 10,000 原始坐标单位', () => {
    const edge = { ...payload.actors[1], actor_id: '5', name: '外环精灵', position: [0, 10000, 0] }
    const wrapper = mount(SceneRadar, { props: { data: parseNearby({ ...payload, actors: [edge] }) } })
    expect(wrapper.text()).toContain('10,000 原始坐标单位')
    expect(wrapper.get('.radar-target').attributes('transform')).toBe('translate(200,380)')
    const far = { ...payload.actors[1], actor_id: '6', name: '更远精灵', position: [12500, 0, 0] }
    const hidden = mount(SceneRadar, { props: { data: parseNearby({ ...payload, actors: [far] }) } })
    expect(hidden.findAll('.radar-target')).toHaveLength(0)
  })
  it('按重点和双牌状态区分雷达目标', () => {
    const double = { ...payload.actors[1], actor_id: '3', name: '双牌精灵', marks: [
      { label: '大', name: '大块头', source: 'reference' },
      { label: '婉', name: '婉转声', source: 'reference' },
    ], attention: 'double', position: [100, 0, 0] }
    const wrapper = mount(SceneRadar, { props: { data: parseNearby({ ...payload, actors: [payload.actors[0], double] }) } })
    expect(wrapper.find('.radar-target.is-marked').exists()).toBe(true)
    expect(wrapper.find('.radar-target.is-double').exists()).toBe(true)
    expect(wrapper.find('.radar-target.is-double .radar-point').attributes('r')).toBe('7')
    expect(wrapper.get('.radar-legend').text()).toContain('重点')
    expect(wrapper.get('.radar-legend').text()).toContain('双牌')
  })
  it('紧凑雷达只在选中目标时显示名称', () => {
    const wrapper = mount(SceneRadar, { props: { data: parseNearby(payload), compact: true, selected: '9007199254740993' } })
    expect(wrapper.get('.radar-target').classes()).toContain('selected')
    expect(wrapper.get('.radar-target-label').text()).toBe('未知精灵')
  })
  it('绘制独立的玩家中心点', () => {
    const wrapper = mount(SceneRadar, { props: { data: parseNearby(payload) } })
    expect(wrapper.find('.radar-player').exists()).toBe(true)
    expect(wrapper.find('.radar-player').classes()).not.toContain('radar-point')
  })
})
