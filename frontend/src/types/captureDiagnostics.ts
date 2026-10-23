export interface DiagnosticCheck {
  id: string; title: string; status: 'ok' | 'error' | 'warning' | 'info' | 'idle' | 'waiting'
  message: string; actions: string[]
}
export interface CaptureDiagnostics {
  diagnostics: DiagnosticCheck[]
  sessions: { session_id: string; has_key: boolean; data_frames: number }[]
  totals: { raw_chunks: number; raw_bytes: number; decrypt_ok: number; decrypt_fail: number; key_miss: number; parse_fail: number }
  event_log_name: string
  iface: string
  port: number
  extra_ports: number[]
  running: boolean
  any_key: boolean
  recording: boolean
  recording_requested: boolean
  autostart: boolean
  automation: { enabled: boolean; audit_guidance: string }
  install: { phase: string; message: string; progress: number | null }
}
export interface CaptureDiagnosticsHost {
  request: (path: string, options?: { method?: string; body?: unknown }) => Promise<unknown>
  publish: (payload: unknown) => void
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
  if (!('port' in value) || typeof value.port !== 'number' || !Number.isInteger(value.port)
      || !('extra_ports' in value) || !Array.isArray(value.extra_ports)
      || !value.extra_ports.every((port: unknown) => typeof port === 'number' && Number.isInteger(port))
      || !('running' in value) || typeof value.running !== 'boolean'
      || !('any_key' in value) || typeof value.any_key !== 'boolean'
      || !('recording' in value) || typeof value.recording !== 'boolean'
      || !('recording_requested' in value) || typeof value.recording_requested !== 'boolean'
      || !('autostart' in value) || typeof value.autostart !== 'boolean'
      || !('automation' in value)) throw new Error('采集设置响应无效')
  const automation = value.automation
  if (!automation || typeof automation !== 'object' || !('enabled' in automation) || typeof automation.enabled !== 'boolean'
      || !('audit_guidance' in automation) || typeof automation.audit_guidance !== 'string') throw new Error('游戏跟随状态无效')
  if (!['environment', 'network', 'capture', 'decrypt'].every(id => diagnostics.some(check => check.id === id))) throw new Error('采集诊断检查项缺失')
  if (!('sessions' in value) || !Array.isArray(value.sessions) || !('totals' in value)
      || !('event_log_name' in value) || typeof value.event_log_name !== 'string') throw new Error('高级诊断响应无效')
  const sessions = value.sessions.map((row: unknown) => {
    if (!row || typeof row !== 'object' || !('session_id' in row) || typeof row.session_id !== 'string'
        || !('has_key' in row) || typeof row.has_key !== 'boolean' || !('data_frames' in row)
        || typeof row.data_frames !== 'number') throw new Error('采集会话响应无效')
    return { session_id: row.session_id, has_key: row.has_key, data_frames: row.data_frames }
  })
  const totals = value.totals
  if (!totals || typeof totals !== 'object'
      || !('raw_chunks' in totals) || typeof totals.raw_chunks !== 'number'
      || !('raw_bytes' in totals) || typeof totals.raw_bytes !== 'number'
      || !('decrypt_ok' in totals) || typeof totals.decrypt_ok !== 'number'
      || !('decrypt_fail' in totals) || typeof totals.decrypt_fail !== 'number'
      || !('key_miss' in totals) || typeof totals.key_miss !== 'number'
      || !('parse_fail' in totals) || typeof totals.parse_fail !== 'number') throw new Error('采集统计响应无效')
  return { diagnostics, sessions, event_log_name: value.event_log_name,
    totals: { raw_chunks: totals.raw_chunks, raw_bytes: totals.raw_bytes, decrypt_ok: totals.decrypt_ok,
      decrypt_fail: totals.decrypt_fail, key_miss: totals.key_miss, parse_fail: totals.parse_fail }, iface: value.iface, port: value.port, extra_ports: value.extra_ports,
    running: value.running, any_key: value.any_key, recording: value.recording,
    recording_requested: value.recording_requested, autostart: value.autostart,
    automation: { enabled: automation.enabled, audit_guidance: automation.audit_guidance },
    install: { phase: install.phase, message: install.message, progress: install.progress } }

}
export function parseIfaces(value: unknown): { name: string; description: string }[] {
  if (!value || typeof value !== 'object' || !('ifaces' in value) || !Array.isArray(value.ifaces)) throw new Error('网卡列表响应无效')
  return value.ifaces.map((row: unknown) => {
    if (!row || typeof row !== 'object' || !('name' in row) || typeof row.name !== 'string'
        || !('description' in row) || typeof row.description !== 'string') throw new Error('网卡信息无效')
    return { name: row.name, description: row.description }
  })
}
