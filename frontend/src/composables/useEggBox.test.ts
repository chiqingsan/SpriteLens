import { effectScope, nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useEggBox } from './useEggBox'
import type { EggBox, EggBoxAnnotations, EggBoxEntry, EggBoxSaveAnnotations } from '../types/eggBox'

const annotations = { nature_id: 0, nest_override: '' as const, note: '', voice_tag: '' as const }

function egg(instanceId: number): EggBoxEntry {
  return {
    instance_id: instanceId, egg_conf_id: 3001001, egg_name: `蛋${instanceId}`, species_name: '',
    chain_names: [], description: '', description_source: '', icon_url: '', fallback_icon_url: '',
    egg_type_name: '', egg_kind: 'regular', egg_group_names: [], hatch_label: '', quantity: 1,
    obtained_at: instanceId, historical: false, hatching: false, hatch_known: false,
    historical_hatching: false, favorite: false, hatch_progress: 0, special_egg_conf_id: 0,
    height_cm: 0, weight_g: 0, home_egg: false, annotations: { ...annotations },
    tags: { nature: '', weight: null, voice: null, medals: [], nest: '' },
    measurement_ranges: { height_cm: null, weight_g: null },
  }
}

const box: EggBox = {
  eggs: [egg(1), egg(2)], uid: 42, total: 2, hatching: null, historical_hatching: 0,
  source: 'observed', version: 1, nature_options: [],
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: Error) => void
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}

const scopes: ReturnType<typeof effectScope>[] = []
afterEach(() => { scopes.splice(0).forEach(scope => scope.stop()) })

function annotationHarness() {
  let uid = 42
  const stored = new Map([42, 84].map(account => [account, { ...structuredClone(box), uid: account }]))
  const payload = () => structuredClone(stored.get(uid)!)
  const requests: { value: EggBoxSaveAnnotations; done: ReturnType<typeof deferred<void>> }[] = []
  const host = {
    load: vi.fn(async () => payload()),
    saveAnnotations: vi.fn((value: EggBoxSaveAnnotations) => {
      const done = deferred<void>()
      requests.push({ value, done })
      return done.promise.then(() => {
        const target = stored.get(value.uid)!.eggs.find(item => item.instance_id === value.instance_id)!
        const { uid: account, instance_id: instanceId, ...saved } = value
        target.annotations = saved
      })
    }),
    saveFavorite: vi.fn(async () => undefined), cancel: vi.fn(), versionChanged: vi.fn(),
  }
  const scope = effectScope()
  scopes.push(scope)
  const model = scope.run(() => useEggBox(host))!
  const shown = () => model.annotationsFor(model.data.value!.eggs[0]!)
  return { model, host, stored, requests, payload, shown,
    async switchAccount(account: number) {
      model.resetAccount(); uid = account; await model.load()
    },
    edit(patch: Partial<EggBoxAnnotations>, save = true) {
      model.updateAnnotations(uid, 1, { ...shown(), ...patch })
      if (save) model.saveAnnotations(uid, 1)
    },
  }
}

describe('useEggBox annotation drafts', () => {
  it('返回复用同版本快照，版本变化和加载失败触发重新加载', async () => {
    const t = annotationHarness(); await t.model.load()
    t.model.pause(); await t.model.resume(1)
    expect(t.host.load).toHaveBeenCalledTimes(1)
    t.stored.get(42)!.version = 2
    await t.model.resume(2)
    expect(t.host.load).toHaveBeenCalledTimes(2)
    t.host.load.mockRejectedValueOnce(new Error('读取失败'))
    await t.model.load(); expect(t.model.error.value).toBe('读取失败')
    t.model.pause(); await t.model.resume(2)
    expect(t.host.load).toHaveBeenCalledTimes(4); expect(t.model.error.value).toBe('')
  })

  it('离页期间保存完成，即使版本推送尚未到达也重新同步快照', async () => {
    const t = annotationHarness(); await t.model.load(); t.edit({ note: 'saved-offscreen' })
    t.model.pause(); t.requests[0]!.done.resolve()
    await vi.waitFor(() => expect(t.stored.get(42)!.eggs[0]!.annotations.note).toBe('saved-offscreen'))
    await t.model.resume(1)
    expect(t.host.load).toHaveBeenCalledTimes(2)
    expect(t.model.data.value!.eggs[0]!.annotations.note).toBe('saved-offscreen')
  })

  it('keeps per-egg drafts while a save is in flight and after selection is cleared', async () => {
    let releaseFirstSave!: () => void
    const firstSave = new Promise<void>(resolve => { releaseFirstSave = resolve })
    const saves: Array<{ uid: number; instance_id: number; nature_id: number; note: string }> = []
    const host = {
      load: vi.fn(async () => box),
      saveAnnotations: vi.fn(async (value: { uid: number; instance_id: number; nature_id: number; note: string }) => {
        saves.push(value)
        if (saves.length === 1) await firstSave
      }),
      saveFavorite: vi.fn(async () => undefined),
      cancel: vi.fn(),
      versionChanged: vi.fn(),
    }
    const scope = effectScope()
    const model = scope.run(() => useEggBox(host))!
    await model.load()

    model.updateAnnotations(42, 1, { ...annotations, nature_id: 1 })
    model.saveAnnotations(42, 1)
    model.select(box.eggs[1])
    model.updateAnnotations(42, 2, { ...annotations, nature_id: 9 })
    model.select(box.eggs[0])
    expect(model.annotationsFor(box.eggs[0]).nature_id).toBe(1)

    model.updateAnnotations(42, 1, { ...model.annotationsFor(box.eggs[0]), note: '只改备注' })
    model.saveAnnotations(42, 1)
    model.clearSelection()
    model.select(box.eggs[0])
    expect(model.annotationsFor(box.eggs[0])).toEqual({ ...annotations, nature_id: 1, note: '只改备注' })

    releaseFirstSave()
    await vi.waitFor(() => expect(saves).toHaveLength(2))
    expect(saves[1]).toMatchObject({ uid: 42, instance_id: 1, nature_id: 1, note: '只改备注' })
    scope.stop()
  })

  it('切号 A→B→A 后同一枚蛋仍串行保存，最新编辑最终落盘', async () => {
    const t = annotationHarness(); await t.model.load()
    t.edit({ note: 'old-1' }); t.edit({ note: 'old-2' })
    await t.switchAccount(84); await t.switchAccount(42)
    t.edit({ note: 'new-3' })
    expect(t.requests).toHaveLength(1)
    t.requests[0]!.done.resolve()
    await vi.waitFor(() => expect(t.requests).toHaveLength(2))
    expect(t.requests[1]!.value).toMatchObject({ uid: 42, instance_id: 1, note: 'new-3' })
    t.requests[1]!.done.resolve()
    await vi.waitFor(() => expect(t.stored.get(42)!.eggs[0]!.annotations.note).toBe('new-3'))
    expect(t.shown().note).toBe('new-3')
  })

  it('旧刷新结束不清理新保存；随后只改性格仍保留新备注', async () => {
    const t = annotationHarness(); await t.model.load()
    const oldRefresh = deferred<EggBox>()
    t.host.load.mockImplementationOnce(() => oldRefresh.promise)
    t.edit({ note: 'saved-old' }); t.requests[0]!.done.resolve()
    await vi.waitFor(() => expect(t.host.load).toHaveBeenCalledTimes(2))
    const oldPayload = t.payload()
    await t.switchAccount(42); t.edit({ note: 'new-draft' })
    oldRefresh.resolve(oldPayload); await oldRefresh.promise; await nextTick()
    expect(t.shown().note).toBe('new-draft')
    t.edit({ nature_id: 7 })
    t.requests[1]!.done.resolve()
    await vi.waitFor(() => expect(t.requests).toHaveLength(3))
    expect(t.requests[2]!.value).toMatchObject({ note: 'new-draft', nature_id: 7 })
    t.requests[2]!.done.resolve()
    await vi.waitFor(() => expect(t.stored.get(42)!.eggs[0]!.annotations).toMatchObject({ note: 'new-draft', nature_id: 7 }))
  })

  it('只读详情采用刷新后的标注，修改备注不回写旧性格', async () => {
    const t = annotationHarness(); await t.model.load(); t.shown()
    t.stored.get(42)!.eggs[0]!.annotations.nature_id = 7
    await t.model.load()
    expect(t.shown().nature_id).toBe(7)
    t.edit({ note: 'only-note' })
    expect(t.requests[0]!.value.nature_id).toBe(7)
    t.requests[0]!.done.resolve()
    await vi.waitFor(() => expect(t.stored.get(42)!.eggs[0]!.annotations).toMatchObject({ nature_id: 7, note: 'only-note' }))
  })

  it('保存失败后切回账号仍保留草稿和错误，可重试落盘', async () => {
    const t = annotationHarness(); await t.model.load(); t.edit({ note: 'retry-me' })
    t.requests[0]!.done.reject(new Error('synthetic disk failure'))
    await vi.waitFor(() => expect(t.model.annotationErrorFor(t.model.data.value!.eggs[0]!)).toBe('synthetic disk failure'))
    await t.switchAccount(84); await t.switchAccount(42)
    expect(t.shown().note).toBe('retry-me')
    expect(t.model.annotationErrorFor(t.model.data.value!.eggs[0]!)).toBe('synthetic disk failure')
    t.model.saveAnnotations(42, 1); t.requests[1]!.done.resolve()
    await vi.waitFor(() => expect(t.stored.get(42)!.eggs[0]!.annotations.note).toBe('retry-me'))
    expect(t.model.annotationErrorFor(t.model.data.value!.eggs[0]!)).toBe('')
  })

  it('在途保存成功后的刷新保留尚未提交的备注草稿', async () => {
    const t = annotationHarness(); await t.model.load(); t.edit({ nature_id: 1 })
    t.edit({ note: 'not-blurred' }, false)
    t.requests[0]!.done.resolve()
    await vi.waitFor(() => expect(t.host.load).toHaveBeenCalledTimes(2))
    await nextTick()
    expect(t.shown()).toMatchObject({ nature_id: 1, note: 'not-blurred' })
    t.model.saveAnnotations(42, 1); t.requests[1]!.done.resolve()
    await vi.waitFor(() => expect(t.stored.get(42)!.eggs[0]!.annotations.note).toBe('not-blurred'))
  })

  it('离页后的旧保存不主动刷新，返回时已保存的干净状态采用后端新值', async () => {
    const t = annotationHarness(); await t.model.load(); t.edit({ nature_id: 1 })
    t.model.pause(); t.requests[0]!.done.resolve()
    await vi.waitFor(() => expect(t.stored.get(42)!.eggs[0]!.annotations.nature_id).toBe(1))
    expect(t.host.load).toHaveBeenCalledTimes(1)
    t.stored.get(42)!.eggs[0]!.annotations.nature_id = 7
    await t.model.load()
    expect(t.shown().nature_id).toBe(7)
  })
})
