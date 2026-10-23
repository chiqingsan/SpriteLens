export interface DiagnosticCheck {
  id: string; title: string; status: 'ok' | 'error' | 'warning' | 'info' | 'idle' | 'waiting'
  message: string; actions: string[]
}
export interface CaptureDiagnostics {
  diagnostics: DiagnosticCheck[]
  iface: string
  install: { phase: string; message: string; progress: number | null }
}
export interface CaptureDiagnosticsHost {
  request: (path: string, options?: { method?: string; body?: unknown }) => Promise<unknown>
  publish: (payload: unknown) => void
  advanced: () => void
}
export function parseCaptureDiagnostics(value: unknown): CaptureDiagnostics {
  if (!value || typeof value !== 'object' || !('diagnostics' in value) || !Array.isArray(value.diagnostics)
      || !('iface' in value) || typeof value.iface !== 'string' || !('install' in value)) {
    throw new Error('采集诊断响应无效')
  }
  const diagnostics = value.diagnostics.map((row: unknown): DiagnosticCheck => {
    if (!row || typeof row !== 'object' || !('id' in row) || typeof row.id !== 'string'
        || !('title' in row) || typeof row.title !== 'string' || !('message' in row) || typeof row.message !== 'string'
        || !('status' in row) || !('actions' in row) || !Array.isArray(row.actions)
        || !row.actions.every((action: unknown) => typeof action === 'string' && ['recheck', 'install', 'rsc', 'ifaces', 'start', 'stop', 'advanced'].includes(action))) throw new Error('采集诊断检查项无效')
    const status = row.status
    if (status !== 'ok' && status !== 'error' && status !== 'warning' && status !== 'info' && status !== 'idle' && status !== 'waiting') throw new Error('采集诊断状态无效')
    return { id: row.id, title: row.title, message: row.message, status, actions: row.actions }
  })
  const install = value.install
  if (!install || typeof install !== 'object' || !('phase' in install) || typeof install.phase !== 'string'
      || !('message' in install) || typeof install.message !== 'string' || !('progress' in install)
      || (install.progress !== null && (typeof install.progress !== 'number' || !Number.isFinite(install.progress)))) throw new Error('安装状态无效')
  return { diagnostics, iface: value.iface, install: { phase: install.phase, message: install.message, progress: install.progress } }
}
export function parseIfaces(value: unknown): { name: string; description: string }[] {
  if (!value || typeof value !== 'object' || !('ifaces' in value) || !Array.isArray(value.ifaces)) throw new Error('网卡列表响应无效')
  return value.ifaces.map((row: unknown) => {
    if (!row || typeof row !== 'object' || !('name' in row) || typeof row.name !== 'string'
        || !('description' in row) || typeof row.description !== 'string') throw new Error('网卡信息无效')
    return { name: row.name, description: row.description }
  })
}
