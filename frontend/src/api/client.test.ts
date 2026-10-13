import { afterEach, expect, it, vi } from 'vitest'
import { createApiClient } from './client'
afterEach(() => vi.unstubAllGlobals())
it('同源鉴权、取消、error/message 与无效 JSON', async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(new Response('{"error":"拒绝访问"}', { status: 401 }))
    .mockResolvedValueOnce(new Response('{"message":"读取失败"}', { status: 500 }))
    .mockResolvedValueOnce(new Response('invalid'))
  vi.stubGlobal('fetch', fetcher)
  const api = createApiClient('test-token')
  const controller = new AbortController()
  await expect(api('/api/eggs', controller.signal)).rejects.toThrow('拒绝访问')
  expect(fetcher).toHaveBeenCalledWith('/api/eggs', { headers: { 'X-Local-Token': 'test-token' }, signal: controller.signal })
  await expect(api('/api/eggs')).rejects.toThrow('读取失败')
  await expect(api('/api/eggs')).rejects.toThrow('无效 JSON')
})
