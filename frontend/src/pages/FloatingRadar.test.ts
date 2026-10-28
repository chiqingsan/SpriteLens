import { mount, flushPromises } from '@vue/test-utils'
import { afterEach, describe, it, expect, vi } from 'vitest'
import FloatingRadar from './FloatingRadar.vue'

vi.stubGlobal('ResizeObserver', class {
  constructor(private callback: ResizeObserverCallback) {}
  observe() { this.callback([{ contentRect: { width: 300, height: 300 } } as ResizeObserverEntry], {} as ResizeObserver) }
  disconnect() {}
})

function channel() { return { onmessage: null, postMessage: vi.fn(), close: vi.fn() } as unknown as BroadcastChannel }
const snapshotPayload = (overrides: Record<string, unknown> = {}) => ({
  uid: '1', version: 1, observation_id: 1, phase: 'observing', complete: false, source: 'observed_partial', mapping_available: true, radar_radius_raw: 10000,
  scene_id: 1, updated_at: 1, unresolved_updates: 0, rejected_actors: 0, player_position: [0, 0, null], position_source: 'client_target',
  actors: [{ actor_id: '9007199254740993', config_id: 1, base_id: 1, name: '单牌精灵', icon_url: '', type_names: [], level: 1,
    height: 0, weight: 0, voice: 100, updated_at: 1, marks: [{ label: '婉', name: '婉转声', source: 'reference' }], attention: 'marked', position: [100, 0, 0] }],
  ...overrides,
})
afterEach(() => { vi.useRealTimers() })
describe('自绘悬浮雷达', () => {
  it('首次快照、清单和底图就绪后一次显示，普通更新不再隐藏', async () => {
    let resolveMap: (value: unknown) => void = () => {}
    const wire = channel()
    const wrapper = mount(FloatingRadar, { props: { channel: wire, host: {
      close: vi.fn(), setOpacity: vi.fn(), loadMaps: () => new Promise(resolve => { resolveMap = resolve }),
    } } })
    expect(wrapper.get('.scene-radar-scope').classes()).toContain('is-preparing')
    wire.onmessage?.({ data: { kind: 'snapshot', payload: snapshotPayload({ resource_id: '10003' }) } } as MessageEvent)
    await flushPromises()
    expect(wrapper.get('.scene-radar-scope').classes()).toContain('is-preparing')
    resolveMap({ schema_version: 1, coordinate_version: 1, maps: { '10003': {
      name: '地图', availability: 'supported', image: { url: '/static/map.webp', width: 4096, height: 4096 },
      projection: { origin_x: 0, origin_y: 0, side: 100000 }, calibration: { level: 'verified' },
    } } })
    await flushPromises()
    expect(wrapper.get('.scene-radar-scope').classes()).toContain('is-preparing')
    await wrapper.get('.radar-map image').trigger('load')
    expect(wrapper.get('.scene-radar-scope').classes()).not.toContain('is-preparing')
    wire.onmessage?.({ data: { kind: 'snapshot', payload: snapshotPayload({ version: 2, resource_id: '10003' }) } } as MessageEvent)
    await flushPromises()
    expect(wrapper.get('.scene-radar-scope').classes()).not.toContain('is-preparing')
    wrapper.unmount()
  })
  it('战前位置和实体接续时提示可能过期，重新确认后清除提示', async () => {
    const wire = channel()
    const wrapper = mount(FloatingRadar, { props: { channel: wire, host: { close: vi.fn(), setOpacity: vi.fn() } } })
    const actor = { ...snapshotPayload().actors[0], stale: true }
    wire.onmessage?.({ data: { kind: 'snapshot', payload: snapshotPayload({ position_source: 'battle_return', actors: [actor] }) } } as MessageEvent)
    await flushPromises()
    expect(wrapper.find('.floating-battle-stale').exists()).toBe(false)
    expect(wrapper.get('.floating-attention-chip').attributes('aria-label')).toContain('可能已过期')
    wire.onmessage?.({ data: { kind: 'snapshot', payload: snapshotPayload({ version: 2 }) } } as MessageEvent)
    await flushPromises()
    expect(wrapper.find('[role="status"]').exists()).toBe(false)
    wrapper.unmount()
  })
  it('慢快照可推进同周期画面，版本较小的新账号也能清空旧图', async () => {
    const wire = channel()
    const wrapper = mount(FloatingRadar, { props: { channel: wire, host: { close: vi.fn(), setOpacity: vi.fn() } } })
    wire.onmessage?.({ data: { kind: 'summary', summary: { uid: '1', version: 100, observation_id: 1, phase: 'observing' } } } as MessageEvent)
    wire.onmessage?.({ data: { kind: 'snapshot', payload: snapshotPayload({ version: 99 }) } } as MessageEvent)
    await flushPromises()
    expect(wrapper.findAll('.radar-target')).toHaveLength(1)
    wire.onmessage?.({ data: { kind: 'summary', summary: { uid: '2', version: 1, observation_id: 1, phase: 'observing' } } } as MessageEvent)
    await flushPromises()
    expect(wrapper.findAll('.radar-target')).toHaveLength(0)
    wire.onmessage?.({ data: { kind: 'snapshot', payload: snapshotPayload({ uid: '1', version: 101 }) } } as MessageEvent)
    await flushPromises()
    expect(wrapper.findAll('.radar-target')).toHaveLength(0)
    wire.onmessage?.({ data: { kind: 'snapshot', payload: snapshotPayload({ uid: '2' }) } } as MessageEvent)
    await flushPromises()
    expect(wrapper.findAll('.radar-target')).toHaveLength(1)
    wrapper.unmount()
  })
  it('透明度命令串行合并，关闭入口调用桌面桥', async () => {
    let resolve: () => void = () => {}
    const host = { close: vi.fn().mockResolvedValue(null), setOpacity: vi.fn().mockImplementationOnce(() => new Promise<void>(r => { resolve = r })).mockResolvedValue(null) }
    const wrapper = mount(FloatingRadar, { props: { channel: channel(), host } })
    expect(wrapper.find('.floating-titlebar').exists()).toBe(true)
    await wrapper.get('[aria-label="雷达设置"]').trigger('click')
    expect(wrapper.get('output').text()).toBe('85%')
    expect(wrapper.get('input').attributes()).toMatchObject({ min: '35', max: '90', step: '1' })
    await wrapper.get('input').setValue('35'); await wrapper.get('input').setValue('70'); await wrapper.get('input').setValue('90')
    expect(host.setOpacity).toHaveBeenCalledTimes(1)
    resolve(); await flushPromises()
    expect(host.setOpacity.mock.calls.map(args => args[0])).toEqual([35, 90])
    await wrapper.get('[aria-label="关闭悬浮雷达"]').trigger('click')
    expect(host.close).toHaveBeenCalledOnce()
    wrapper.unmount()
  })
  it('失败恢复已确认透明度并明确报错', async () => {
    const host = { close: vi.fn(), setOpacity: vi.fn().mockRejectedValue(Error('透明度设置失败')) }
    const wrapper = mount(FloatingRadar, { props: { channel: channel(), host } })
    await wrapper.get('[aria-label="雷达设置"]').trigger('click')
    await wrapper.get('input').setValue('50'); await flushPromises()
    expect(wrapper.get('output').text()).toBe('85%')
    expect(wrapper.get('[role="alert"]').text()).toContain('透明度设置失败')
    wrapper.unmount()
  })
  it('卸载后不发送排队的透明度设置', async () => {
    let resolve: () => void = () => {}
    const host = { close: vi.fn(), setOpacity: vi.fn(() => new Promise<void>(r => { resolve = r })) }
    const wrapper = mount(FloatingRadar, { props: { channel: channel(), host } })
    await wrapper.get('[aria-label="雷达设置"]').trigger('click')
    await wrapper.get('input').setValue('35'); await wrapper.get('input').setValue('60')
    wrapper.unmount(); resolve(); await flushPromises()
    expect(host.setOpacity).toHaveBeenCalledTimes(1)
  })
  it('在标题栏显示图例，并用单牌胶囊关联雷达目标', async () => {
    const wire = channel()
    const wrapper = mount(FloatingRadar, { props: { channel: wire, host: { close: vi.fn(), setOpacity: vi.fn() } } })
    wire.onmessage?.({ data: { kind: 'snapshot', payload: {
      uid: '1', version: 1, observation_id: 1, phase: 'observing', complete: false, source: 'observed_partial', mapping_available: true, radar_radius_raw: 10000,
      scene_id: 1, updated_at: 1, unresolved_updates: 0, rejected_actors: 0, player_position: [0, 0, null], position_source: 'client_target',
      actors: [{ actor_id: '9007199254740993', config_id: 1, base_id: 1, name: '单牌精灵', icon_url: '/static/pet.png', type_names: [], level: 1,
        height: 0, weight: 0, voice: 100, updated_at: 1, marks: [{ label: '婉', name: '婉转声', source: 'reference' }], attention: 'marked', position: [100, 0, 0] }]
    } } } as MessageEvent)
    await flushPromises()
    expect(wrapper.get('.floating-legend').text()).toContain('普通')
    expect(wrapper.get('.floating-legend').text()).toContain('双牌')
    expect(wrapper.get('.floating-attention-chip').text()).not.toContain('单牌精灵')
    expect(wrapper.get('.floating-attention-chip').attributes('aria-label')).toContain('单牌精灵')
    expect(wrapper.get('.floating-attention-chip img').attributes('src')).toBe('/static/pet.png')
    expect(wrapper.find('.radar-attention-ring').exists()).toBe(true)
    expect(wrapper.find('.radar-player').exists()).toBe(true)
    await wrapper.get('.floating-attention-chip').trigger('click')
    expect(wrapper.get('.radar-target').classes()).toContain('selected')
    wrapper.unmount()
  })
  it('无标记数据时仍保留固定的胶囊布局槽位', () => {
    const wrapper = mount(FloatingRadar, { props: { channel: channel(), host: { close: vi.fn(), setOpacity: vi.fn() } } })
    expect(wrapper.get('.floating-attention-slot').exists()).toBe(true)
    expect(wrapper.get('.floating-attention-list').classes()).toContain('is-empty')
    wrapper.unmount()
  })
  it('有标记胶囊按双牌满、双牌、单牌满、单牌排序', async () => {
    const wire = channel()
    const actor = (actor_id: string, attention: 'marked' | 'double', marks: string[]) => ({
      actor_id, config_id: 1, base_id: 1, name: actor_id, icon_url: '', type_names: [], level: 1,
      height: 0, weight: 0, voice: 0, updated_at: Number(actor_id), attention,
      position: [Number(actor_id), 0, 0], marks: marks.map(name => ({ label: name, name, source: 'reference' as const }))
    })
    const wrapper = mount(FloatingRadar, { props: { channel: wire, host: { close: vi.fn(), setOpacity: vi.fn() } } })
    wire.onmessage?.({ data: { kind: 'snapshot', payload: {
      uid: '1', version: 1, observation_id: 1, phase: 'observing', complete: false, source: 'observed_partial', mapping_available: true, radar_radius_raw: 10000,
      scene_id: 1, updated_at: 1, unresolved_updates: 0, rejected_actors: 0, player_position: [0, 0, null], position_source: 'client_target',
      actors: [actor('1', 'marked', ['大块头']), actor('2', 'double', ['大块头', '婉转声']), actor('3', 'marked', ['婉转声', '满分']), actor('4', 'double', ['小不点', '满重', '粗嗓门', '满分'])]
    } } } as MessageEvent)
    await flushPromises()
    expect(await wrapper.findAll('.floating-attention-chip').map(chip => chip.attributes('aria-label'))).toEqual([
      '4，双牌', '2，双牌', '3，单牌', '1，单牌'
    ])
    wrapper.unmount()
  })
  it('炫彩精灵进入顶部条：头像挂星标、胶囊置顶', async () => {
    const wire = channel()
    const base = { config_id: 1, base_id: 1, type_names: [], level: 1, height: 0, weight: 0, voice: 0, updated_at: 1, position: [1, 0, 0] }
    const wrapper = mount(FloatingRadar, { props: { channel: wire, host: { close: vi.fn(), setOpacity: vi.fn() } } })
    wire.onmessage?.({ data: { kind: 'snapshot', payload: {
      uid: '1', version: 1, observation_id: 1, phase: 'observing', complete: false, source: 'observed_partial', mapping_available: true, radar_radius_raw: 10000,
      scene_id: 1, updated_at: 1, unresolved_updates: 0, rejected_actors: 0, player_position: [0, 0, null], position_source: 'client_target',
      actors: [
        { ...base, actor_id: '1', name: '单牌精灵', icon_url: '/static/pet.png', attention: 'marked', marks: [{ label: '婉', name: '婉转声', source: 'reference' as const }] },
        { ...base, actor_id: '2', name: '炫彩精灵', icon_url: '/static/pet.png', attention: 'normal', colorful: true, mutation: 8, marks: [] },
      ],
    } } } as MessageEvent)
    await flushPromises()
    const chips = wrapper.findAll('.floating-attention-chip')
    // 炫彩即使没有单/双牌也进顶部条，并排在有牌精灵之前。
    expect(chips.map(chip => chip.attributes('aria-label'))).toEqual(['炫彩精灵，炫彩', '单牌精灵，单牌'])
    expect(chips[0].classes()).toContain('is-colorful')
    expect(chips[0].get('.floating-attention-colorful').attributes('src')).toBe('/static/rarity/colorful-fit.webp')
    expect(chips[0].get('.floating-attention-avatar img').attributes('src')).toBe('/static/pet.png')
    expect(wrapper.get('.floating-legend').text()).not.toContain('炫彩')
    wrapper.unmount()
  })
  it('超过 3 秒无消息时清空实体并提示，恢复心跳后自动清除', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'Date'] })
    const wire = channel()
    const wrapper = mount(FloatingRadar, { props: { channel: wire, host: { close: vi.fn(), setOpacity: vi.fn() } } })
    wire.onmessage?.({ data: { kind: 'snapshot', payload: snapshotPayload() } } as MessageEvent)
    await flushPromises()
    expect(wrapper.findAll('.radar-target')).toHaveLength(1)
    expect(wrapper.find('.floating-attention-chip').exists()).toBe(true)
    vi.advanceTimersByTime(4000)
    await flushPromises()
    expect(wrapper.findAll('.radar-target')).toHaveLength(0)
    expect(wrapper.find('.floating-attention-chip').exists()).toBe(false)
    expect(wrapper.get('[role="alert"]').text()).toContain('数据已失效（采集连接断开或主窗口未响应）')
    wire.onmessage?.({ data: { kind: 'ping' } } as MessageEvent)
    await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wire.postMessage).toHaveBeenLastCalledWith({ kind: 'subscribe' })
    wrapper.unmount()
  })
  it('发布失败消息时清空旧图并报错', async () => {
    const wire = channel()
    const wrapper = mount(FloatingRadar, { props: { channel: wire, host: { close: vi.fn(), setOpacity: vi.fn() } } })
    wire.onmessage?.({ data: { kind: 'snapshot', payload: snapshotPayload() } } as MessageEvent)
    await flushPromises()
    expect(wrapper.findAll('.radar-target')).toHaveLength(1)
    wire.onmessage?.({ data: { kind: 'error', message: '附近刷新失败' } } as MessageEvent)
    await flushPromises()
    expect(wrapper.findAll('.radar-target')).toHaveLength(0)
    expect(wrapper.get('[role="alert"]').text()).toContain('附近刷新失败')
    wrapper.unmount()
  })
  it('刷新失败消息时保留同周期旧图并标注可能过期', async () => {
    const wire = channel()
    const wrapper = mount(FloatingRadar, { props: { channel: wire, host: { close: vi.fn(), setOpacity: vi.fn() } } })
    wire.onmessage?.({ data: { kind: 'snapshot', payload: snapshotPayload() } } as MessageEvent)
    await flushPromises()
    await wrapper.get('.floating-attention-chip').trigger('click')
    expect(wrapper.get('.radar-target').classes()).toContain('selected')
    wire.onmessage?.({ data: { kind: 'stale', message: '网络断开' } } as MessageEvent)
    await flushPromises()
    expect(wrapper.findAll('.radar-target')).toHaveLength(1)
    expect(wrapper.get('.floating-attention-chip').exists()).toBe(true)
    expect(wrapper.get('[role="status"]').text()).toContain('刷新失败，显示的是稍早的结果')
    expect(wrapper.get('.radar-target').classes()).toContain('selected')
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    // 心跳只证明主窗口还活着，不代表刷新成功：过期提示要等真实快照到达才清除。
    wire.onmessage?.({ data: { kind: 'ping' } } as MessageEvent)
    await flushPromises()
    expect(wrapper.find('[role="status"]').exists()).toBe(true)
    wrapper.unmount()
  })
  it('收到新快照后清除刷新失败提示', async () => {
    const wire = channel()
    const wrapper = mount(FloatingRadar, { props: { channel: wire, host: { close: vi.fn(), setOpacity: vi.fn() } } })
    wire.onmessage?.({ data: { kind: 'snapshot', payload: snapshotPayload() } } as MessageEvent)
    wire.onmessage?.({ data: { kind: 'stale', message: '网络断开' } } as MessageEvent)
    await flushPromises()
    expect(wrapper.get('[role="status"]').text()).toContain('刷新失败')
    wire.onmessage?.({ data: { kind: 'snapshot', payload: snapshotPayload({ version: 2 }) } } as MessageEvent)
    await flushPromises()
    expect(wrapper.find('[role="status"]').exists()).toBe(false)
    expect(wrapper.findAll('.radar-target')).toHaveLength(1)
    wrapper.unmount()
  })
  it('无数据时失败消息进入错误空态，收到快照后恢复', async () => {
    const wire = channel()
    const wrapper = mount(FloatingRadar, { props: { channel: wire, host: { close: vi.fn(), setOpacity: vi.fn() } } })
    wire.onmessage?.({ data: { kind: 'error', message: '附近刷新失败' } } as MessageEvent)
    await flushPromises()
    expect(wrapper.findAll('.radar-target')).toHaveLength(0)
    expect(wrapper.get('[role="alert"]').text()).toContain('附近刷新失败')
    wire.onmessage?.({ data: { kind: 'snapshot', payload: snapshotPayload() } } as MessageEvent)
    await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.findAll('.radar-target')).toHaveLength(1)
    wrapper.unmount()
  })
  it('按快照的原始坐标半径缩放雷达', async () => {
    const wire = channel()
    const wrapper = mount(FloatingRadar, { props: { channel: wire, host: { close: vi.fn(), setOpacity: vi.fn() } } })
    const actor = { ...snapshotPayload().actors[0], actor_id: '7', name: '边界精灵', position: [3000, 0, 0] }
    wire.onmessage?.({ data: { kind: 'snapshot', payload: snapshotPayload({ radar_radius_raw: 2500, actors: [actor] }) } } as MessageEvent)
    await flushPromises()
    expect(wrapper.findAll('.radar-target')).toHaveLength(0)
    wire.onmessage?.({ data: { kind: 'snapshot', payload: snapshotPayload({ version: 2, actors: [actor] }) } } as MessageEvent)
    await flushPromises()
    expect(wrapper.findAll('.radar-target')).toHaveLength(1)
    wrapper.unmount()
  })
})
