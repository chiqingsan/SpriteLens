import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi } from 'vitest'
import CaptureDiagnostics from './CaptureDiagnostics.vue'
const payload = { sessions: [], totals: { raw_chunks: 0, raw_bytes: 0, decrypt_ok: 0, decrypt_fail: 0, key_miss: 0, parse_fail: 0 }, event_log_name: '', iface: '', port: 8195, extra_ports: [10012], running: false, any_key: false,
  recording: false, recording_requested: false, autostart: false,
  automation: { enabled: false, audit_guidance: '' }, diagnostics: [
    { id: 'environment', title: '环境检查', status: 'ok', message: '驱动就绪', actions: ['recheck'] },
    { id: 'network', title: '网卡与端口', status: 'info', message: '默认网卡', actions: ['ifaces'] },
    { id: 'capture', title: '采集检查', status: 'idle', message: '未启动', actions: ['start'] },
    { id: 'decrypt', title: '解密检查', status: 'waiting', message: '等待密钥', actions: ['advanced'] },
  ], install: { phase: 'idle', message: '', progress: null } }
describe('统一采集设置', () => {
  it('重复点击只发起一次探测，失败保留结果并可重试', async () => {
    let rejectProbe: (e: Error) => void = () => {}
    const request = vi.fn().mockResolvedValueOnce(payload).mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectProbe = reject })).mockResolvedValue(payload)
    const wrapper = mount(CaptureDiagnostics, { props: { host: { request, publish: vi.fn() } } })
    await flushPromises()
    await wrapper.get('.capture-diagnostic-toggle').trigger('click')
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
  it('正常时只保留统一状态，环境异常或安装失败自动展开诊断', async () => {
    const wrapper = mount(CaptureDiagnostics, { props: { host: { request: vi.fn().mockResolvedValue(payload), publish: vi.fn() } } })
    await flushPromises()
    expect(wrapper.text()).toContain('环境正常')
    expect(wrapper.text()).not.toContain('WinPcap')
    expect(wrapper.find('#capture-connection-details').exists()).toBe(false)
    wrapper.vm.update({ ...payload, diagnostics: payload.diagnostics.map(check => check.id === 'environment' ? { ...check, status: 'error', message: '缺驱动', actions: ['recheck', 'install'] } : check) })
    await flushPromises()
    expect(wrapper.text()).toContain('WinPcap')
    expect(wrapper.text()).toContain('安装 Npcap')
    wrapper.vm.update({ ...payload, install: { phase: 'failed', message: '安装失败', progress: null } })
    await flushPromises()
    expect(wrapper.text()).toContain('安装失败')
    wrapper.vm.update(payload); await flushPromises()
    expect(wrapper.find('#capture-connection-details').exists()).toBe(false)
    wrapper.unmount()
  })
  it('设置保存失败恢复勾选状态，成功后才确认新选择', async () => {
    const request = vi.fn().mockResolvedValueOnce(payload).mockRejectedValueOnce(new Error('保存失败')).mockResolvedValue({ ...payload, autostart: true })
    const wrapper = mount(CaptureDiagnostics, { props: { host: { request, publish: vi.fn() } } })
    await flushPromises()
    const checkbox = wrapper.get('input[type="checkbox"]')
    await checkbox.setValue(true); await flushPromises()
    expect(request).toHaveBeenLastCalledWith('/api/capture/autostart', { method: 'POST', body: { enabled: true } })
    expect((checkbox.element as HTMLInputElement).checked).toBe(false)
    expect(wrapper.text()).toContain('保存失败')
    await checkbox.setValue(true); await flushPromises()
    expect((checkbox.element as HTMLInputElement).checked).toBe(true)
    wrapper.unmount()
  })
  it('游戏跟随和录制沿用原命令，未采集时禁用立即录制', async () => {
    const request = vi.fn().mockResolvedValue(payload)
    const wrapper = mount(CaptureDiagnostics, { props: { host: { request, publish: vi.fn() } } })
    await flushPromises()
    expect(wrapper.findAll('button').find(button => button.text() === '开始录制')!.attributes('disabled')).toBeDefined()
    await wrapper.findAll('input[type="checkbox"]')[1]!.setValue(true); await flushPromises()
    expect(request).toHaveBeenLastCalledWith('/api/capture/automation', { method: 'POST', body: { enabled: true } })
    await wrapper.findAll('input[type="checkbox"]')[2]!.setValue(true); await flushPromises()
    expect(request).toHaveBeenLastCalledWith('/api/capture/recording', { method: 'POST', body: { enabled: true } })
    wrapper.unmount()
  })
  it('配置游戏跟随时显示等待状态，完成前不提前勾选', async () => {
    let finish: (value: unknown) => void = () => {}
    const request = vi.fn().mockResolvedValueOnce(payload).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const wrapper = mount(CaptureDiagnostics, { props: { host: { request, publish: vi.fn() } } })
    await flushPromises()
    const checkbox = wrapper.findAll('input[type="checkbox"]')[1]!
    await checkbox.setValue(true)
    expect(wrapper.get('[role="status"]').text()).toContain('正在启用游戏跟随')
    expect((checkbox.element as HTMLInputElement).checked).toBe(false)
    expect(checkbox.attributes('disabled')).toBeDefined()
    finish({ ...payload, automation: { ...payload.automation, enabled: true } }); await flushPromises()
    expect((checkbox.element as HTMLInputElement).checked).toBe(true)
    expect(wrapper.text()).not.toContain('正在启用游戏跟随')
    wrapper.unmount()
  })
  it('展开一次就能使用高级诊断并应用密钥', async () => {
    const request = vi.fn().mockResolvedValueOnce(payload).mockResolvedValueOnce({ ok: true, message: '密钥已应用' }).mockResolvedValue(payload)
    const wrapper = mount(CaptureDiagnostics, { props: { host: { request, publish: vi.fn() } } })
    await flushPromises()
    await wrapper.get('.capture-diagnostic-toggle').trigger('click')
    expect(wrapper.find('.capture-connection #capture-connection-details').exists()).toBe(true)
    expect(wrapper.text()).toContain('高级诊断')
    expect(wrapper.text()).toContain('暂无会话')
    await wrapper.get('#capture-manual-key').setValue('0123456789abcdef')
    await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(request).toHaveBeenCalledWith('/api/capture/key', { method: 'POST', body: { text: '0123456789abcdef' } })
    expect(wrapper.text()).toContain('密钥已应用')
    wrapper.unmount()
  })
  it('密钥应用失败保留输入并显示错误，不发布成功状态', async () => {
    const publish = vi.fn()
    const request = vi.fn().mockResolvedValueOnce(payload).mockRejectedValueOnce(new Error('密钥无效'))
    const wrapper = mount(CaptureDiagnostics, { props: { host: { request, publish } } })
    await flushPromises(); publish.mockClear()
    await wrapper.get('.capture-diagnostic-toggle').trigger('click')
    await wrapper.get('#capture-manual-key').setValue('invalid')
    await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('密钥无效')
    expect((wrapper.get('#capture-manual-key').element as HTMLInputElement).value).toBe('invalid')
    expect(publish).not.toHaveBeenCalled()
    wrapper.unmount()
  })
  it('卸载后旧请求不发布状态', async () => {
    let resolve: (value: unknown) => void = () => {}
    const publish = vi.fn()
    const request = vi.fn(() => new Promise(r => { resolve = r }))
    const wrapper = mount(CaptureDiagnostics, { props: { host: { request, publish } } })
    wrapper.unmount(); resolve(payload); await flushPromises()
    expect(publish).not.toHaveBeenCalled()
  })
  it('错误 DTO 不进入壳，空态提供重试', async () => {
    const publish = vi.fn()
    const wrapper = mount(CaptureDiagnostics, { props: { host: { request: vi.fn().mockResolvedValue({}), publish } } })
    await flushPromises()
    expect(wrapper.text()).toContain('响应无效')
    expect(wrapper.text()).toContain('尚无采集设置')
    expect(publish).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
