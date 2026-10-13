export function createApiClient(token: string) {
  return async (path: string, signal?: AbortSignal): Promise<unknown> => {
    const response = await fetch(path, { headers: { 'X-Local-Token': token }, signal })
    const data: unknown = await response.json().catch(() => null)
    if (!response.ok) {
      const message = data && typeof data === 'object'
        ? ('message' in data ? data.message : 'error' in data ? data.error : null) : null
      throw new Error(typeof message === 'string' ? message : `HTTP ${response.status}`)
    }
    if (data === null) throw new Error('服务返回了无效 JSON')
    return data
  }
}
export type ApiClient = ReturnType<typeof createApiClient>
