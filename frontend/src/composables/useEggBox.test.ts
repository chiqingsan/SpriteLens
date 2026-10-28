import { effectScope, nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useEggBox } from './useEggBox'
import type { EggBox, EggBoxAnnotations, EggBoxEntry, EggBoxSaveAnnotations } from '../types/eggBox'

const annotations = { nature_id: 0, nest_override: '' as const, note: '', voice_tag: '' as const, voice_db: null }

function egg(instanceId: number): EggBoxEntry {
  return {
    instance_id: instanceId, egg_conf_id: 3001001, egg_name: `蛋${instanceId}`, species_name: '', dex_no: 0,
    chain_names: [], description: '', description_source: '', icon_url: '', fallback_icon_url: '',
    egg_type_name: '', egg_kind: 'regular', egg_group_names: [], hatch_label: '', quantity: 1,
    obtained_at: instanceId, historical: false, hatching: false, hatch_known: false,
    historical_hatching: false, favorite: false, hatch_progress: 0, special_egg_conf_id: 0,
    height_cm: 0, weight_g: 0, home_egg: false, pickup: null, category: 0,
    from_player_name: '', from_pet_name: '', from_player_uin: 0, from_pet_gid: 0,
    annotations: { ...annotations },
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
  it('图鉴 ID 按数值升序，同编号按时间，未知编号靠后并保留收藏置顶', async () => {
    const t = annotationHarness()
    t.stored.get(42)!.eggs = [10, 2, 2, 0, 0].map((dexNo, index) => ({ ...egg(index + 1), dex_no: dexNo }))
    await t.model.load()
    t.model.filters.sort = 'dex'
    const ids = () => t.model.visibleEggs.value.map(item => item.instance_id)
    expect(ids()).toEqual([3, 2, 1, 5, 4])
    t.model.filters.ascending = true
    expect(ids()).toEqual([2, 3, 1, 4, 5])
    t.model.setFavorite(1, true)
    expect(ids()).toEqual([2, 3, 1, 4, 5])
    t.model.pause(); await t.model.resume(1)
    expect(ids()).toEqual([1, 2, 3, 4, 5])
  })

  it('收藏状态立即更新，后台同步保留位置，返回页面时才应用收藏置顶', async () => {
    const t = annotationHarness(); await t.model.load()
    const ids = () => t.model.visibleEggs.value.map(item => item.instance_id)
    expect(ids()).toEqual([2, 1])
    t.model.setFavorite(1, true)
    t.stored.get(42)!.eggs[0]!.favorite = true
    expect(t.model.data.value!.eggs[0]!.favorite).toBe(true)
    expect(ids()).toEqual([2, 1])
    await t.model.load()
    expect(ids()).toEqual([2, 1])
    t.model.pause(); await t.model.resume(1)
    expect(ids()).toEqual([1, 2])
    expect(t.host.load).toHaveBeenCalledTimes(2)
    t.model.setFavorite(1, false)
    t.stored.get(42)!.eggs[0]!.favorite = false
    await t.model.load()
    expect(ids()).toEqual([1, 2])
    t.model.filters.ascending = true
    expect(ids()).toEqual([1, 2])
    t.model.filters.ascending = false
    expect(ids()).toEqual([2, 1])
    t.model.setFavorite(1, true)
    t.model.filters.sort = 'large'
    expect(ids()).toEqual([1, 2])
  })

  it('重量按五档标签排序，同档按时间；学院绿窝在前，收藏仍置顶', async () => {
    const t = annotationHarness()
    const eggs = Array.from({ length: 10 }, (_, index) => egg(index + 1))
    eggs.forEach((item, index) => {
      const label = ['满重', '大块头', '', '小不点', '底重'][Math.floor(index / 2)]!
      if (label === '大块头' || label === '小不点') item.tags.medals = [label]
      else item.tags.weight = label || null
      // 跨物种的绝对克重不能替代五档标签。
      item.weight_g = index * 1000
    })
    eggs[0]!.tags.nest = '学院绿窝'
    eggs[8]!.tags.nest = '学院绿窝'
    t.stored.get(42)!.eggs = eggs
    await t.model.load()
    const ids = () => t.model.visibleEggs.value.map(item => item.instance_id)
    expect(ids()).toEqual([10, 9, 8, 7, 6, 5, 4, 3, 2, 1])
    t.model.filters.sort = 'large'
    expect(ids()).toEqual([2, 1, 4, 3, 6, 5, 8, 7, 10, 9])
    t.model.filters.sort = 'small'
    expect(ids()).toEqual([10, 9, 8, 7, 6, 5, 4, 3, 2, 1])
    t.model.filters.ascending = true
    expect(ids()).toEqual([9, 10, 7, 8, 5, 6, 3, 4, 1, 2])
    t.model.filters.ascending = false
    t.model.filters.sort = 'academy'
    expect(ids()).toEqual([9, 1, 10, 8, 7, 6, 5, 4, 3, 2])
    t.model.setFavorite(2, true)
    t.model.filters.sort = 'large'
    expect(ids()[0]).toBe(2)
    await t.switchAccount(84)
    expect(ids()).toEqual([2, 1])
  })

  it('关闭前 flush 保存尚未失焦的声音，并等待服务端确认', async () => {
    const t = annotationHarness(); await t.model.load()
    t.edit({ voice_db: -20 }, false)
    let completed = false
    const flushing = t.model.flush().then(() => { completed = true })
    await Promise.resolve()
    expect(completed).toBe(false)
    expect(t.requests[0]!.value.voice_db).toBe(-20)
    t.requests[0]!.done.resolve()
    await flushing
    expect(t.stored.get(42)!.eggs[0]!.annotations.voice_db).toBe(-20)
  })
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
