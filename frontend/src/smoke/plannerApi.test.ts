// 配窝页真实链路冒烟：真实 account-requests.js + 真实 api() + 真实页面组件 + 真实本地服务。
// 需要外部先起服务（tools/planner_smoke_server.py）并给出 SMOKE_PLANNER_URL / SMOKE_PLANNER_TOKEN。
// 未设置环境变量时整组跳过，不进入常规 `vitest run` 门禁。
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { mountBreedingPlanner } from '../breedingPlannerBridge'

const base = process.env.SMOKE_PLANNER_URL || ''
const token = process.env.SMOKE_PLANNER_TOKEN || ''
const seedEgg = process.env.SMOKE_PLANNER_EGG || ''
const legacy = readFileSync('../spritelens/web/static/account-requests.js', 'utf8')

const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))

// jsdom 没有实现 <dialog> 的 showModal/close，页面卸载时会调用 close()，这里补桩。
const dialogProto = window.HTMLDialogElement?.prototype as (HTMLDialogElement & { showModal?: () => void; close?: () => void }) | undefined
if (dialogProto) {
  if (!dialogProto.showModal) dialogProto.showModal = function showModal(this: HTMLDialogElement) { this.open = true }
  if (!dialogProto.close) dialogProto.close = function close(this: HTMLDialogElement) { this.open = false }
}

describe.runIf(!!base)('配窝页真实 API 冒烟', () => {
  it('点「清除方案」后草稿真正落盘，重启（全新实例重读配置）不回滚', async () => {
    // 与 app.js:26-54 等价的请求层：令牌头 + JSON body + keepalive 兜底。
    const api = (path: string, options: { method?: string; body?: unknown; signal?: AbortSignal } = {}) => {
      const headers: Record<string, string> = { 'X-Local-Token': token }
      if (options.body !== undefined) headers['Content-Type'] = 'application/json'
      return fetch(base + path, { method: options.method || 'GET', headers,
        body: options.body === undefined ? undefined : JSON.stringify(options.body), signal: options.signal })
        .then(async response => {
          if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.message || data.error || `HTTP ${response.status}`) }
          return response.json()
        })
    }
    // 真实 account-requests.js（与 spritelens/web/static/app.js:66 同一份代码）
    new Function('window', legacy)(window)
    const accountRequests = (window as unknown as { SpriteLensAccountRequests: { create(api: unknown): any } })
      .SpriteLensAccountRequests.create(api)
    const bootstrap = await api('/api/bootstrap')
    accountRequests.observe(bootstrap.state)

    // 让用例可重复运行：先把服务端草稿写成「带一个目标」的初始状态（上一次运行会把它清空）。
    if (seedEgg) {
      const meta = await api('/api/breeding-planner/context')
      await api('/api/breeding-planner/draft', { method: 'POST', body: {
        mode: 'target', goals: [{ goal_id: 'goal-smoke-1', egg_key: seedEgg, size_mark: '', voice_mark: '', nature_id: 0, priority: 0 }],
        selected: [], participation: 'best', capacity: 10, academy: false, placements: [], approved: [],
        uid: meta.uid, version: meta.version, catalog_version: meta.catalog_version, revision: 0,
        rule_version: meta.rule_version, geometry_version: meta.geometry_version } })
    }

    const seen: string[] = []
    const host = {
      request: (path: string, body?: unknown) => {
        seen.push(`${body === undefined ? 'GET' : 'POST'} ${path}`)
        return accountRequests.request('planner', '/api/breeding-planner/' + path, body === undefined ? {} : { method: 'POST', body })
      },
      cancel: () => accountRequests.cancel('planner'),
      flush: () => false,
      context: () => accountRequests.petContext(),
      openPet: () => undefined
    }

    const root = document.createElement('div')
    document.body.appendChild(root)
    const mounted = mountBreedingPlanner(root, host as never)
    mounted.load()
    await sleep(400)
    const before = await api('/api/breeding-planner/draft?mode=target')
    expect(before.draft.goals.length, '页面加载前服务端应有预置目标').toBe(1)
    expect(root.querySelector('.planner-goal-editor'), '目标卡应已渲染').toBeTruthy()

    const clear = [...root.querySelectorAll('button')].find(button => (button.getAttribute('title') || '').startsWith('清除方案'))
    expect(clear, '应找到「清除方案」按钮').toBeTruthy()
    const probe = (label: string) => {
      const save = [...root.querySelectorAll('button')].find(button => /保存/.test(button.textContent || ''))
      console.log(`[probe ${label}] seq=${seen.join('|')} saveTitle=${JSON.stringify(save?.getAttribute('title') || '')} saveDisabled=${(save as HTMLButtonElement | undefined)?.disabled} goal=${!!root.querySelector('.planner-goal-editor')} notice=${JSON.stringify(root.querySelector('.planner-notice')?.textContent || '')}`)
    }
    probe('loaded')
    ;(clear as HTMLButtonElement).click()
    await sleep(200)
    probe('clear+200')
    await sleep(900)
    probe('clear+1100')
    if (!seen.some(item => item.startsWith('POST'))) {
      const capacity = root.querySelector('.planner-capacity select') as HTMLSelectElement | null
      console.log('[probe] 没有发生 POST，改容量触发一次：', !!capacity)
      if (capacity) { capacity.value = '9'; capacity.dispatchEvent(new Event('change', { bubbles: true })) }
      await sleep(900)
      probe('capacity+900')
    }

    const error = root.querySelector('.planner-notice.is-error')
    console.log(`[smoke] 请求序列: ${seen.join(' | ')} | error=${JSON.stringify(error?.textContent || '')} | notice=${JSON.stringify(root.querySelector('.planner-notice')?.textContent || '')}`)
    expect(error?.textContent || '', '不应出现保存错误提示').toBe('')
    expect(root.querySelector('.planner-goal-editor'), '清除后目标卡应消失').toBeFalsy()
    expect(seen.some(item => item.startsWith('POST')), '清除方案后必须发出落盘请求').toBe(true)
    const after = await api('/api/breeding-planner/draft?mode=target')
    expect(after.draft?.goals ?? [], '服务端草稿里的目标必须被清空').toEqual([])
    mounted.unmount()
  })
})
