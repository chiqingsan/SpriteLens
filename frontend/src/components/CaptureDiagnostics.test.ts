import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi } from 'vitest'
import CaptureDiagnostics from './CaptureDiagnostics.vue'
const payload = { iface: '', diagnostics: [{ id: 'environment', title: '环境检查', status: 'ok', message: '驱动就绪', actions: ['recheck'] }], install: { phase: 'idle', message: '', progress: null } }
describe('采集诊断请求生命周期', () => {
  it('重复点击只发起一次探测，失败保留结果并可重试', async () => {
    let rejectProbe: (e: Error) => void = () => {}
    const request = vi.fn().mockResolvedValueOnce(payload).mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectProbe = reject })).mockResolvedValue(payload)
    const wrapper = mount(CaptureDiagnostics, { props: { host: { request, publish: vi.fn(), advanced: vi.fn() } } })
    await flushPromises()
    const button = wrapper.findAll('button').find(b => b.text() === '重新检测环境')!
    await button.trigger('click'); await button.trigger('click')
    expect(request).toHaveBeenCalledTimes(2)
    rejectProbe(new Error('探测失败')); await flushPromises()
    expect(wrapper.text()).toContain('驱动就绪')
    expect(wrapper.get('[role="alert"]').text()).toContain('探测失败')
    await button.trigger('click'); await flushPromises()
    expect(request).toHaveBeenCalledTimes(3)
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    wrapper.unmount()
  })
  it('卸载后旧请求不发布状态', async () => {
    let resolve: (value: unknown) => void = () => {}
    const publish = vi.fn()
    const request = vi.fn(() => new Promise(r => { resolve = r }))
    const wrapper = mount(CaptureDiagnostics, { props: { host: { request, publish, advanced: vi.fn() } } })
    wrapper.unmount(); resolve(payload); await flushPromises()
    expect(publish).not.toHaveBeenCalled()
  })
  it('错误 DTO 不进入壳，空态提供重试', async () => {
    const publish = vi.fn()
    const wrapper = mount(CaptureDiagnostics, { props: { host: { request: vi.fn().mockResolvedValue({}), publish, advanced: vi.fn() } } })
    await flushPromises()
    expect(wrapper.text()).toContain('响应无效')
    expect(wrapper.text()).toContain('尚无诊断结果')
    expect(publish).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
