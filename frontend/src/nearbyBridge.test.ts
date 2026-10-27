import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

const source = readFileSync(resolve(process.cwd(), '../spritelens/web/static/nearby-page.js'), 'utf8')
const summary = { uid: '101', version: 10, observation_id: 1, phase: 'observing' }
const messages: Array<{ kind: string; payload?: typeof summary; message?: string }> = []
let wire: { onmessage: (event: { data: { kind: string } }) => void }
let bridge: { update(value: unknown): void; suspend(): void; resume(): void; unmount(): void }
function setup(request: ReturnType<typeof vi.fn>) {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'] })
  messages.length = 0
  class Channel {
    onmessage = () => {}
    constructor() { wire = this }
    postMessage(value: typeof messages[number]) { messages.push(value) }
    close() {}
  }
  const host = { addEventListener: vi.fn(), removeEventListener: vi.fn(), setTimeout, clearTimeout, setInterval, clearInterval }
  const create = new Function('window', 'BroadcastChannel', source + '\nreturn window.SpriteLensNearby.create;')(host, Channel)
  bridge = create(request, 'synthetic-token')
  bridge.update(summary)
  wire.onmessage({ data: { kind: 'subscribe' } })
}
afterEach(() => { bridge?.unmount(); vi.useRealTimers() })
describe('附近主窗口与悬浮窗桥接', () => {
  it('慢请求期间合并推送，返回后发布进展并补一次读取', async () => {
    let finish: (value: unknown) => void = () => {}
    const request = vi.fn().mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
      .mockResolvedValueOnce({ ...summary, version: 12 })
    setup(request)
    bridge.update({ ...summary, version: 11 }); bridge.update({ ...summary, version: 12 })
    expect(request).toHaveBeenCalledTimes(1)
    finish(summary); await flushPromises()
    expect(request).toHaveBeenCalledTimes(2)
    expect(messages.filter(m => m.kind === 'snapshot').map(m => m.payload?.version)).toEqual([12])
  })
  it('低版本切号立即取消旧请求，晚到结果不转发', async () => {
    let finish: (value: unknown) => void = () => {}
    const request = vi.fn().mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
      .mockResolvedValueOnce({ ...summary, uid: '202', version: 1 })
    setup(request)
    const signal = request.mock.calls[0]![1].signal as AbortSignal
    bridge.update({ ...summary, uid: '202', version: 1 })
    expect(signal.aborted).toBe(true)
    finish(summary); await flushPromises()
    expect(messages.filter(m => m.kind === 'snapshot').map(m => m.payload?.uid)).toEqual(['202'])
  })
  it('读取超时终止请求并可重试；同周期失败只标记稍早结果', async () => {
    const request = vi.fn().mockResolvedValueOnce(summary).mockImplementationOnce((_path, { signal }) => new Promise((_resolve, reject) => {
      signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
    })).mockResolvedValueOnce({ ...summary, version: 12 })
    setup(request); await flushPromises()
    bridge.update({ ...summary, version: 11 })
    vi.advanceTimersByTime(8000); await flushPromises()
    expect(messages.find(m => m.kind === 'stale')?.message).toContain('超时')
    bridge.update({ ...summary, version: 12 }); await flushPromises()
    expect(messages.filter(m => m.kind === 'snapshot').at(-1)?.payload?.version).toBe(12)
  })
  it('短暂断连不清空，持续断连清空并取消悬挂请求', async () => {
    const request = vi.fn((_path: string, _options: { signal: AbortSignal }) => new Promise(() => {}))
    setup(request)
    bridge.suspend(); vi.advanceTimersByTime(1500); bridge.resume()
    expect(messages.some(m => m.kind === 'error')).toBe(false)
    bridge.suspend(); vi.advanceTimersByTime(3000)
    expect(messages.at(-1)?.kind).toBe('error')
    expect(request.mock.calls[0]![1].signal.aborted).toBe(true)
    const count = request.mock.calls.length
    wire.onmessage({ data: { kind: 'subscribe' } })
    expect(request).toHaveBeenCalledTimes(count)
  })
  it('REST 先于推送观察到新周期时仍转发当前快照', async () => {
    const request = vi.fn().mockResolvedValueOnce({ ...summary, version: 11, observation_id: 2 })
    setup(request); await flushPromises()
    expect(messages.filter(m => m.kind === 'snapshot').at(-1)?.payload?.observation_id).toBe(2)
  })
})
