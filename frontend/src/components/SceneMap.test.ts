import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SceneMap from './SceneMap.vue'
import type { NearbyCoverage, NearbySnapshot } from '../types/nearby'
import type { WorldMapEntry } from '../types/worldMap'

const MAP: WorldMapEntry = {
  name: '卡洛西亚大陆',
  availability: 'supported',
  image: { url: '/static/maps/10003.webp', width: 4096, height: 4096 },
  projection: { origin_x: 306000, origin_y: 408000, side: 408000 },
  calibration: { level: 'verified' },
}

function snapshot(overrides: Partial<NearbySnapshot> = {}): NearbySnapshot {
  return {
    uid: '1', version: 1, observation_id: 1, phase: 'observing',
    player_position: [306000, 408000, 0], position_source: 'client_target',
    debug_coordinates: false, resource_id: '10003', instance_id: null, scene_id: 103,
    updated_at: 1, complete: false, unresolved_updates: 0, rejected_actors: 0,
    radar_radius_raw: 10000, type_icons: {}, mapping_available: true,
    actors: [{
      position: [308000, 410000, 0], actor_id: '11', config_id: 11, base_id: null, name: '迪莫',
      icon_url: '', type_names: [], level: 10, height: 12, weight: 18, voice: 1, updated_at: 1,
      chain_names: [], marks: [{ label: '粗', name: '粗嗓门', source: 'reference' }], attention: 'marked',
    }],
    ...overrides,
  }
}

function ready(wrapper: ReturnType<typeof mount>) {
  return wrapper.find('.scene-map-image').trigger('load')
}
/** 与 MAP 同图：uid/map_id 必须与快照一致，否则组件按归属校验拒绝绘制。 */
const COVERAGE: NearbyCoverage = {
  uid: '1', map_id: '10003', layer: 'visit', scope: 'session',
  revision: 1, cell_size: 2000, cells: 3, rows: [[204, 153, 1], [204, 154, 2]],
}

describe('场景地图', () => {
  beforeEach(() => {
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(640)
    vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(600)
    vi.stubGlobal('ResizeObserver', class {
      observe() {}
      unobserve() {}
      disconnect() {}
    })
  })
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('只把落在地图覆盖范围内的实体画成点位', async () => {
    const wrapper = mount(SceneMap, {
      props: {
        data: snapshot({ actors: [snapshot().actors[0]!, { ...snapshot().actors[0]!, actor_id: '12', name: '越界精灵', position: [9000000, 0, 0] }] }),
        map: MAP,
      },
    })
    await ready(wrapper)
    expect(wrapper.findAll('.scene-map-marker')).toHaveLength(1)
    wrapper.unmount()
  })

  it('点击点位把实体编号回传给页面', async () => {
    const wrapper = mount(SceneMap, { props: { data: snapshot(), map: MAP } })
    await ready(wrapper)
    await wrapper.get('.scene-map-marker').trigger('click')
    expect(wrapper.emitted('select')?.[0]).toEqual(['11'])
    wrapper.unmount()
  })

  it('选中目标的标签优先出现，普通精灵不铺标签', async () => {
    const data = snapshot({
      actors: [
        snapshot().actors[0]!,
        { ...snapshot().actors[0]!, actor_id: '12', name: '普通精灵', attention: 'normal', marks: [] },
      ],
    })
    const wrapper = mount(SceneMap, { props: { data, map: MAP, selected: '11' } })
    await ready(wrapper)
    const labels = wrapper.findAll('.scene-map-label').map(label => label.text())
    expect(labels).toContain('迪莫')
    expect(labels).not.toContain('普通精灵')
    wrapper.unmount()
  })

  it('缺玩家位置时只显示等待提示，不画假光标', async () => {
    const wrapper = mount(SceneMap, { props: { data: snapshot({ player_position: null, position_source: null }), map: MAP } })
    await ready(wrapper)
    expect(wrapper.find('.scene-map-player').exists()).toBe(false)
    expect(wrapper.get('.scene-map-state').text()).toContain('等待参考位置')
    wrapper.unmount()
  })

  it('普通精灵只在悬停或聚焦时临时出标签', async () => {
    const data = snapshot({
      actors: [{ ...snapshot().actors[0]!, actor_id: '12', name: '普通精灵', attention: 'normal', marks: [] }],
    })
    const wrapper = mount(SceneMap, { props: { data, map: MAP } })
    await ready(wrapper)
    const marker = wrapper.get('.scene-map-marker')
    expect(wrapper.findAll('.scene-map-label').map(label => label.text())).not.toContain('普通精灵')
    await marker.trigger('pointerenter')
    expect(wrapper.findAll('.scene-map-label').map(label => label.text())).toContain('普通精灵')
    await marker.trigger('pointerleave')
    expect(wrapper.findAll('.scene-map-label').map(label => label.text())).not.toContain('普通精灵')
    wrapper.unmount()
  })

  it('底图失败时可重试，重试会换掉图片请求', async () => {
    const wrapper = mount(SceneMap, { props: { data: snapshot(), map: MAP } })
    await wrapper.get('.scene-map-image').trigger('error')
    expect(wrapper.get('.scene-map-state.is-error').text()).toContain('底图加载失败')
    await wrapper.get('.scene-map-state .scene-map-button').trigger('click')
    expect(wrapper.get('.scene-map-image').attributes('src')).toBe('/static/maps/10003.webp?retry=1')
    wrapper.unmount()
  })

  it('普通数据刷新不重置视角，换场景或实例才回到全图', async () => {
    const wrapper = mount(SceneMap, { props: { data: snapshot(), map: MAP } })
    await wrapper.get('.scene-map-viewport').trigger('wheel', { deltaY: -300 })
    const zoomed = wrapper.get('.scene-map-stage').attributes('style')
    await wrapper.setProps({ data: snapshot({ version: 2 }) })
    expect(wrapper.get('.scene-map-stage').attributes('style')).toBe(zoomed)
    await wrapper.setProps({ sceneKey: '10003:42' })
    expect(wrapper.get('.scene-map-stage').attributes('style')).not.toBe(zoomed)
    wrapper.unmount()
  })

  it('缩放不暂停跟随，点跟随才暂停、点定位恢复', async () => {
    const wrapper = mount(SceneMap, { props: { data: snapshot(), map: MAP } })
    await ready(wrapper)
    const followButton = () => wrapper.get('[data-action="follow"]')
    expect(followButton().attributes('aria-pressed')).toBe('true')
    await wrapper.get('.scene-map-viewport').trigger('wheel', { deltaY: -300 })
    expect(followButton().attributes('aria-pressed')).toBe('true')
    await followButton().trigger('click')
    expect(followButton().attributes('aria-pressed')).toBe('false')
    await wrapper.get('[data-action="locate"]').trigger('click')
    expect(followButton().attributes('aria-pressed')).toBe('true')
    wrapper.unmount()
  })

  it('展示覆盖格网：fill/border/mask 复用同一条路径，失效快照不保留过去实体', async () => {
    const wrapper = mount(SceneMap, { props: { data: snapshot({ coverage: { ...COVERAGE, radius_raw: 9000 } }), map: MAP } })
    await ready(wrapper)
    const d = wrapper.get('.map-coverage-fill').attributes('d')
    expect(d).toBeTruthy()
    // rows 两个 run → 两条矩形子路径。
    expect(d!.match(/M/g)).toHaveLength(2)
    expect(wrapper.get('.map-coverage-border').attributes('d')).toBe(d)
    expect(wrapper.get('.map-coverage mask path').attributes('d')).toBe(d)
    await wrapper.setProps({ data: null })
    expect(wrapper.find('.map-coverage').exists()).toBe(false)
    expect(wrapper.findAll('.scene-map-marker')).toHaveLength(0)
    wrapper.unmount()
  })

  it('没有覆盖或归属不匹配时不渲染覆盖路径', async () => {
    const none = mount(SceneMap, { props: { data: snapshot(), map: MAP } })
    await ready(none)
    expect(none.find('.map-coverage').exists()).toBe(false)
    const otherMap = mount(SceneMap, { props: { data: snapshot({ coverage: { ...COVERAGE, map_id: '10018' } }), map: MAP } })
    await ready(otherMap)
    expect(otherMap.find('.map-coverage').exists()).toBe(false)
    const otherAccount = mount(SceneMap, { props: { data: snapshot({ coverage: { ...COVERAGE, uid: '2' } }), map: MAP } })
    await ready(otherAccount)
    expect(otherAccount.find('.map-coverage').exists()).toBe(false)
    none.unmount(); otherMap.unmount(); otherAccount.unmount()
  })

  it('隐藏视图不挂载覆盖层，恢复显示后才生成路径', async () => {
    const wrapper = mount(SceneMap, { props: { data: snapshot({ coverage: COVERAGE }), map: MAP, visible: false } })
    await ready(wrapper)
    expect(wrapper.find('.map-coverage').exists()).toBe(false)
    await wrapper.setProps({ visible: true })
    expect(wrapper.get('.map-coverage-fill').attributes('d')).toBeTruthy()
    wrapper.unmount()
  })

  it('图例使用本次足迹口径，显示格数且不写已扫描', async () => {
    const wrapper = mount(SceneMap, { props: { data: snapshot({ coverage: { ...COVERAGE, radius_raw: 9000 } }), map: MAP } })
    await ready(wrapper)
    const legend = wrapper.get('.scene-map-legend')
    expect(legend.text()).toContain('记录范围 · 3 格')
    expect(legend.text()).toContain('估计半径 约 90 米')
    expect(legend.text()).toContain('未记录')
    expect(legend.text()).not.toContain('已扫描')
    wrapper.unmount()
    const blank = mount(SceneMap, { props: { data: snapshot(), map: MAP } })
    await ready(blank)
    expect(blank.get('.scene-map-legend').text()).not.toContain('记录范围 ·')
    blank.unmount()
  })

  it('视口外的实体不生成点位，避免 3 倍缩放下全量建节点', async () => {
    const data = snapshot({
      actors: [
        snapshot().actors[0]!,
        { ...snapshot().actors[0]!, actor_id: '12', name: '屏幕外精灵', position: [400000, 500000, 0] },
      ],
    })
    const wrapper = mount(SceneMap, { props: { data, map: MAP } })
    await ready(wrapper)
    expect(wrapper.findAll('.scene-map-marker')).toHaveLength(1)
    wrapper.unmount()
  })

  it('密集场景只渲染最近 160 个点位且选中项始终保留', async () => {
    const actors = Array.from({ length: 200 }, (_, index) => ({
      ...snapshot().actors[0]!,
      actor_id: String(900 + index),
      name: '精灵' + index,
      position: [306000 + index * 40, 408000 + index * 10, 0],
      attention: 'normal' as const,
      marks: [],
    }))
    const wrapper = mount(SceneMap, { props: { data: snapshot({ actors }), map: MAP, selected: '1099' } })
    await ready(wrapper)
    expect(wrapper.findAll('.scene-map-marker')).toHaveLength(160)
    expect(wrapper.findAll('.scene-map-marker.selected')).toHaveLength(1)
    expect(wrapper.get('.scene-map-legend').text()).toContain('显示 160 / 200 个，优先选中和有标记的精灵')
    wrapper.unmount()
  })

  it('工具栏指针按下不进入地图拖动', async () => {
    const wrapper = mount(SceneMap, { props: { data: snapshot(), map: MAP } })
    await ready(wrapper)
    await wrapper.get('[data-action="zoom-in"]').trigger('pointerdown')
    expect(wrapper.get('.scene-map-viewport').classes()).not.toContain('is-dragging')
    wrapper.unmount()
  })

  it('底图失败时重试按钮指针按下不进入地图拖动', async () => {
    const wrapper = mount(SceneMap, { props: { data: snapshot(), map: MAP } })
    await wrapper.get('.scene-map-image').trigger('error')
    await wrapper.get('.scene-map-state .scene-map-button').trigger('pointerdown')
    expect(wrapper.get('.scene-map-viewport').classes()).not.toContain('is-dragging')
    wrapper.unmount()
  })
})
