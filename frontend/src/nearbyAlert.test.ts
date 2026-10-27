import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

const alertSource = readFileSync(resolve(process.cwd(), '../spritelens/web/static/nearby-alert.js'), 'utf8')
const pageSource = readFileSync(resolve(process.cwd(), '../spritelens/web/static/nearby-page.js'), 'utf8')

interface StorageLike { getItem(key: string): string | null; setItem(key: string, value: string): void }
interface AlertOptions { storage?: StorageLike | null; now?: () => number; play?: () => void }
interface AlertApi { evaluate(payload: unknown): void; enabled(): boolean; toggle(next?: boolean): boolean; dispose(): void }
interface PageBridge { update(value: unknown): void; suspend(): void; resume(): void; unmount(): void }

function windowStub(extra: Record<string, unknown> = {}) {
  return { addEventListener: vi.fn(), removeEventListener: vi.fn(), ...extra }
}
function loadAlert(windowHost: Record<string, unknown>, options: AlertOptions): AlertApi {
  const create = new Function('window', alertSource + '\nreturn window.SpriteLensNearbyAlert.create;')(windowHost) as (value: AlertOptions) => AlertApi
  return create(options)
}
function actor(actorId: string, attention: string) { return { actor_id: actorId, attention } }
function snapshot(actors: unknown[], extra: Record<string, unknown> = {}) {
  return { uid: '101', version: 10, observation_id: 1, phase: 'observing', actors, ...extra }
}

describe('附近精灵提醒音引擎', () => {
  it('空闲时预备音频，用户手势恢复；关闭时取消尚未执行的预备任务', () => {
    let idle: () => void = () => {}
    const resume = vi.fn(() => Promise.resolve())
    const close = vi.fn(() => Promise.resolve())
    const createAudio = vi.fn(function (this: { state: string; resume: typeof resume; close: typeof close }) {
      this.state = 'suspended'; this.resume = resume; this.close = close
    })
    const host = windowStub({ AudioContext: createAudio, requestIdleCallback: vi.fn((fn: () => void) => { idle = fn; return 7 }), cancelIdleCallback: vi.fn() })
    const alert = loadAlert(host, { storage: null })
    expect(createAudio).not.toHaveBeenCalled()
    idle()
    expect(createAudio).toHaveBeenCalledTimes(1)
    const pointer = host.addEventListener.mock.calls.find(([name]) => name === 'pointerdown')![1] as () => void
    pointer()
    expect(resume).toHaveBeenCalledTimes(1)
    alert.dispose()
    expect(close).toHaveBeenCalledTimes(1)

    const pending = loadAlert(host, { storage: null })
    pending.dispose()
    expect(host.cancelIdleCallback).toHaveBeenCalledWith(7)
  })
  it('首次快照不响；新增单牌不响，新增双牌响一次', () => {
    const play = vi.fn()
    const alert = loadAlert(windowStub(), { storage: null, now: () => 0, play })
    expect(alert.enabled()).toBe(true)
    alert.evaluate(snapshot([actor('1', 'normal')]))
    expect(play).not.toHaveBeenCalled()
    alert.evaluate(snapshot([actor('1', 'normal'), actor('2', 'marked')]))
    expect(play).not.toHaveBeenCalled()
    alert.evaluate(snapshot([actor('1', 'normal'), actor('2', 'marked'), actor('3', 'double')]))
    expect(play).toHaveBeenCalledTimes(1)
  })
  it('同一份快照里多个双牌只响一次，单牌不补响', () => {
    const play = vi.fn()
    const alert = loadAlert(windowStub(), { storage: null, now: () => 0, play })
    alert.evaluate(snapshot([]))
    alert.evaluate(snapshot([actor('1', 'marked'), actor('2', 'double'), actor('3', 'double'), actor('4', 'normal')]))
    expect(play).toHaveBeenCalledTimes(1)
  })
  it('普通精灵新增不响', () => {
    const play = vi.fn()
    const alert = loadAlert(windowStub(), { storage: null, now: () => 0, play })
    alert.evaluate(snapshot([actor('1', 'normal')]))
    alert.evaluate(snapshot([actor('1', 'normal'), actor('2', 'normal')]))
    expect(play).not.toHaveBeenCalled()
  })
  it('同周期实体消失后超过冷却时间重新出现时再次提醒', () => {
    let clock = 0
    const play = vi.fn()
    const alert = loadAlert(windowStub(), { storage: null, now: () => clock, play })
    alert.evaluate(snapshot([actor('7', 'double')]))
    alert.evaluate(snapshot([], { version: 11 }))
    clock = 600001
    alert.evaluate(snapshot([actor('7', 'double')], { version: 12 }))
    expect(play).toHaveBeenCalledTimes(2)
    alert.dispose()
  })
  it('同一实体十分钟内跨周期或短暂消失重现不重复响，冷却后重现再响', () => {
    const play = vi.fn()
    let clock = 0
    const alert = loadAlert(windowStub(), { storage: null, now: () => clock, play })
    alert.evaluate(snapshot([], { observation_id: 1 }))
    alert.evaluate(snapshot([actor('7', 'double')], { observation_id: 2 }))
    expect(play).toHaveBeenCalledTimes(1)
    alert.evaluate(snapshot([], { observation_id: 2 }))
    alert.evaluate(snapshot([actor('7', 'double')], { observation_id: 2 }))
    expect(play).toHaveBeenCalledTimes(1)
    alert.evaluate(snapshot([actor('7', 'double')], { observation_id: 3 }))
    expect(play).toHaveBeenCalledTimes(1)
    clock = 9 * 60 * 1000
    alert.evaluate(snapshot([], { observation_id: 4 }))
    alert.evaluate(snapshot([actor('7', 'double')], { observation_id: 5 }))
    expect(play).toHaveBeenCalledTimes(1)
    clock = 10 * 60 * 1000 + 1
    alert.evaluate(snapshot([actor('7', 'double')], { observation_id: 6 }))
    expect(play).toHaveBeenCalledTimes(2)
  })
  it('存储为 0 时默认关闭，切换会持久化、试听一次并重建基线', () => {
    const play = vi.fn()
    const storage = { getItem: vi.fn(() => '0'), setItem: vi.fn() }
    const alert = loadAlert(windowStub(), { storage, now: () => 0, play })
    expect(alert.enabled()).toBe(false)
    alert.evaluate(snapshot([actor('5', 'double')]))
    expect(play).not.toHaveBeenCalled()
    expect(alert.toggle(true)).toBe(true)
    expect(alert.enabled()).toBe(true)
    expect(play).toHaveBeenCalledTimes(1)
    expect(storage.setItem).toHaveBeenCalledWith('spritelens.nearby.sound', '1')
    /* 开启后的第一份快照只建基线：已有双牌不补响，之后新出现的双牌才响，新增单牌不响。 */
    alert.evaluate(snapshot([actor('5', 'double')]))
    expect(play).toHaveBeenCalledTimes(1)
    alert.evaluate(snapshot([actor('5', 'double'), actor('6', 'double')]))
    expect(play).toHaveBeenCalledTimes(2)
    alert.evaluate(snapshot([actor('5', 'double'), actor('6', 'double'), actor('7', 'marked')]))
    expect(play).toHaveBeenCalledTimes(2)
    expect(alert.toggle(false)).toBe(false)
    expect(storage.setItem).toHaveBeenLastCalledWith('spritelens.nearby.sound', '0')
  })
  it('非法载荷不抛错不响，迟到的旧观察被忽略', () => {
    const play = vi.fn()
    const alert = loadAlert(windowStub(), { storage: null, now: () => 0, play })
    expect(() => {
      alert.evaluate(null)
      alert.evaluate(undefined)
      alert.evaluate('snapshot')
      alert.evaluate(42)
      alert.evaluate({})
      alert.evaluate({ uid: '101', observation_id: 1 })
      alert.evaluate({ uid: {}, observation_id: 1, actors: [] })
      alert.evaluate({ uid: '101', observation_id: '1', actors: [] })
      alert.evaluate(snapshot([null, 'actor', { actor_id: 3, attention: 'marked' }, { actor_id: '3', attention: 'weird' }]))
    }).not.toThrow()
    expect(play).not.toHaveBeenCalled()
    alert.evaluate(snapshot([], { observation_id: 5 }))
    alert.evaluate(snapshot([actor('9', 'double')], { observation_id: 4 }))
    expect(play).not.toHaveBeenCalled()
    alert.evaluate(snapshot([actor('9', 'double')], { observation_id: 6 }))
    expect(play).toHaveBeenCalledTimes(1)
  })
  it('同一观察周期的旧版本不会倒退并触发提醒', () => {
    const play = vi.fn()
    const alert = loadAlert(windowStub(), { storage: null, now: () => 0, play })
    alert.evaluate(snapshot([actor('9', 'normal')], { version: 12 }))
    alert.evaluate(snapshot([actor('9', 'double')], { version: 11 }))
    expect(play).not.toHaveBeenCalled()
  })
  it('dispose 移除手势监听且之后调用不抛错', () => {
    const windowHost = windowStub()
    const alert = loadAlert(windowHost, { storage: null, now: () => 0, play: vi.fn() })
    expect(windowHost.addEventListener).toHaveBeenCalledTimes(2)
    alert.dispose()
    expect(windowHost.removeEventListener).toHaveBeenCalledTimes(2)
    expect(() => alert.evaluate(snapshot([actor('1', 'double')]))).not.toThrow()
    expect(() => alert.dispose()).not.toThrow()
  })
})

describe('提醒音与附近壳层供数', () => {
  const summary = { uid: '101', version: 10, observation_id: 1, phase: 'observing' }
  const messages: Array<{ kind: string; payload?: unknown; message?: string }> = []
  let wire: { onmessage: (event: { data: { kind: string } }) => void }
  let bridge: PageBridge
  function audioWindow(storageValue: string | null) {
    const windowHost: Record<string, any> = {
      addEventListener: vi.fn(), removeEventListener: vi.fn(),
      /* 延迟到调用时再取全局实现，才能被 setupBridge 里的假定时器接管。 */
      setTimeout: (fn: () => void, ms: number) => setTimeout(fn, ms),
      clearTimeout: (id: number) => clearTimeout(id),
      setInterval: (fn: () => void, ms: number) => setInterval(fn, ms),
      clearInterval: (id: number) => clearInterval(id),
      localStorage: { getItem: vi.fn(() => storageValue), setItem: vi.fn() },
      __toneStarts: 0
    }
    class AudioContextStub {
      currentTime = 0
      state = 'suspended'
      destination = {}
      resume = vi.fn(() => Promise.resolve())
      close = vi.fn(() => Promise.resolve())
      createOscillator() {
        return {
          type: '', frequency: { setValueAtTime: vi.fn() }, connect: vi.fn(), stop: vi.fn(),
          start: vi.fn(() => { windowHost.__toneStarts += 1 })
        }
      }
      createGain() {
        return { gain: { setValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn() }, connect: vi.fn() }
      }
    }
    windowHost.AudioContext = AudioContextStub
    return windowHost
  }
  function setupBridge(windowHost: Record<string, any>, request: ReturnType<typeof vi.fn>) {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'] })
    messages.length = 0
    class Channel {
      onmessage = () => {}
      constructor() { wire = this }
      postMessage(value: typeof messages[number]) { messages.push(value) }
      close() {}
    }
    new Function('window', alertSource)(windowHost)
    const create = new Function('window', 'BroadcastChannel', pageSource + '\nreturn window.SpriteLensNearby.create;')(windowHost, Channel) as (request: unknown, token: string) => PageBridge
    bridge = create(request, 'synthetic-token')
  }
  afterEach(() => { bridge?.unmount(); vi.useRealTimers() })

  it('页面未挂载时按摘要变化取快照，双牌响、单牌不响；推送密集时合并供数', async () => {
    const request = vi.fn()
      .mockResolvedValueOnce(snapshot([actor('7', 'double')]))
      .mockResolvedValueOnce(snapshot([actor('7', 'double'), actor('8', 'marked')], { version: 12 }))
      .mockResolvedValueOnce(snapshot([actor('7', 'double'), actor('8', 'marked'), actor('9', 'double')], { version: 13 }))
    const windowHost = audioWindow(null)
    setupBridge(windowHost, request)
    /* 首份快照立即取，作为提醒基线。 */
    bridge.update(summary)
    expect(request).toHaveBeenCalledTimes(1)
    await flushPromises()
    expect(windowHost.__toneStarts).toBe(2)
    /* 2 秒内的多次推送合并为一次尾随读取，不按推送次数放大请求。 */
    bridge.update({ ...summary, version: 12 })
    expect(request).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(2000)
    await flushPromises()
    expect(request).toHaveBeenCalledTimes(2)
    expect(windowHost.__toneStarts).toBe(2)
    bridge.update({ ...summary, version: 13 })
    expect(request).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(2000)
    await flushPromises()
    expect(request).toHaveBeenCalledTimes(3)
    expect(windowHost.__toneStarts).toBe(4)
    expect(messages.some(message => message.kind === 'snapshot')).toBe(false)
  })
  it('提醒音关闭时不为声音额外取数', async () => {
    const request = vi.fn().mockResolvedValue(snapshot([actor('7', 'marked')]))
    const windowHost = audioWindow('0')
    setupBridge(windowHost, request)
    bridge.update(summary)
    expect(request).not.toHaveBeenCalled()
    bridge.update({ ...summary, version: 12 })
    await flushPromises()
    expect(request).not.toHaveBeenCalled()
    expect(windowHost.__toneStarts).toBe(0)
  })
})
