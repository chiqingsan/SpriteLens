<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import UiIcon from './UiIcon.vue'
import { parseCaptureDiagnostics, parseIfaces } from '../types/captureDiagnostics'
import type { CaptureDiagnostics, CaptureDiagnosticsHost, DiagnosticCheck } from '../types/captureDiagnostics'
const props = defineProps<{ host: CaptureDiagnosticsHost }>()
const data = ref<CaptureDiagnostics | null>(null)
const automationProgress = ref('')
const keyText = ref(''), keyMessage = ref('')
const error = ref(''), busy = ref(false), selected = ref(''), showDetails = ref(false)
const ifaces = ref<{ name: string; description: string }[]>([])
let active = true
const sessionLabels: Record<string, string> = { waiting_key: '等待密钥', waiting_identity: '等待身份', parse_error: '解析失败', observing: '正常', stopped: '已停止' }
function activityTime(value: number) { return value ? new Date(value * 1000).toLocaleTimeString() : '尚未收到数据' }
const labels: Record<string, string> = { recheck: '重新检测环境', install: '安装 Npcap', rsc: '禁用 RSC' }
const environment = computed(() => data.value?.diagnostics.find(check => check.id === 'environment'))
const capture = computed(() => data.value?.diagnostics.find(check => check.id === 'capture'))
const decrypt = computed(() => data.value?.diagnostics.find(check => check.id === 'decrypt'))
const warning = computed(() => data.value?.diagnostics.find(check => check.id === 'warnings'))
const installing = computed(() => data.value !== null && !['idle', 'completed', 'failed'].includes(data.value.install.phase))
const environmentNeedsHelp = computed(() => environment.value?.status === 'error' || environment.value?.status === 'warning'
  || installing.value || data.value?.install.phase === 'failed')
const summary = computed(() => {
  if (!data.value) return { title: '正在读取连接状态', message: '请稍候…' }
  if (environmentNeedsHelp.value) return { title: installing.value ? '正在准备采集环境' : '采集环境需要处理', message: '请查看下方诊断，完成环境设置。' }
  if (capture.value?.status === 'error') return { title: '采集遇到问题', message: '请查看诊断信息后重试。' }
  if (!data.value.running) return { title: '采集未启动', message: '开始采集后进入游戏；已登录时请重新进入。' }
  if (capture.value?.status === 'waiting') return { title: '等待游戏数据', message: '采集已启动，已登录时请重新进入游戏。' }
  if (decrypt.value?.status === 'ok') return { title: '已观察到游戏数据', message: '已收到可解密的数据，累计记录可在诊断中查看。' }
  return { title: data.value.any_key ? '等待解密数据' : '等待游戏登录', message: '保持采集开启，进入游戏后会继续更新。' }
})
const stages = computed(() => [
  { id: 'environment', check: environment.value, label: environment.value?.status === 'ok' ? '环境正常' : environment.value?.status === 'waiting' ? '检测环境中' : '环境待处理' },
  { id: 'capture', check: capture.value, label: data.value?.running ? '采集中' : '未采集' },
  { id: 'decrypt', check: decrypt.value, label: decrypt.value?.status === 'ok' ? '已解密' : data.value?.any_key ? '已有密钥' : '等待密钥' },
])
const missingSelected = computed(() => selected.value && !ifaces.value.some(row => row.name === selected.value))
const ports = computed(() => data.value ? [data.value.port, ...data.value.extra_ports].join(' · ') : '')
const detailChecks = computed(() => data.value?.diagnostics.filter(check => check.id !== 'network' && check.id !== 'warnings') ?? [])
watch(environmentNeedsHelp, needsHelp => { showDetails.value = needsHelp })
watch(() => capture.value?.status, status => { if (status === 'error') showDetails.value = true })
function icon(check: DiagnosticCheck | undefined) { return check?.status === 'ok' ? 'circle-check' : check?.status === 'error' || check?.status === 'warning' ? 'activity' : 'clock' }
function update(value: unknown) {
  if (!active) return
  try { data.value = parseCaptureDiagnostics(value); selected.value = data.value.iface; return true }
  catch (e) { error.value = e instanceof Error ? e.message : String(e) }
}
async function run(action: string, enabled?: boolean) {
  if (busy.value || !active) return
  busy.value = true; error.value = ''
  if (action === 'automation') automationProgress.value = enabled ? '正在启用游戏跟随，配置 Windows 任务可能需要数秒…' : '正在关闭游戏跟随，移除 Windows 任务可能需要数秒…'
  try {
    if (action === 'ifaces') {
      const result = await props.host.request('/api/capture/ifaces')
      if (active) ifaces.value = parseIfaces(result)
    } else {
      const paths: Record<string, string> = { load: '', recheck: '/environment', install: '/npcap/install', rsc: '/rsc', start: '/start', stop: '/stop', select: '/iface', autostart: '/autostart', automation: '/automation', recording: '/recording' }
      const body = action === 'select' ? { name: selected.value } : enabled === undefined ? undefined : { enabled }
      const result = await props.host.request('/api/capture' + paths[action], action === 'load' ? undefined : { method: 'POST', ...(body === undefined ? {} : { body }) })
      if (active && update(result)) props.host.publish(result)
    }
  } catch (e) {
    if (active) { error.value = e instanceof Error ? e.message : String(e); selected.value = data.value?.iface ?? ''; showDetails.value = true }
  } finally { if (active) { busy.value = false; automationProgress.value = '' } }
}
async function applyKey() {
  if (busy.value || !active) return
  const text = keyText.value.trim()
  if (!text) { keyMessage.value = '请先粘贴密钥文本'; return }
  busy.value = true; error.value = ''; keyMessage.value = ''
  try {
    const result = await props.host.request('/api/capture/key', { method: 'POST', body: { text } })
    if (!active) return
    if (!result || typeof result !== 'object' || !('ok' in result) || typeof result.ok !== 'boolean'
        || !('message' in result) || typeof result.message !== 'string') throw new Error('密钥应用响应无效')
    if (!result.ok) throw new Error(result.message)
    keyMessage.value = result.message; keyText.value = ''
    const snapshot = await props.host.request('/api/capture')
    if (active && update(snapshot)) props.host.publish(snapshot)
  } catch (e) {
    if (active) error.value = e instanceof Error ? e.message : String(e)
  } finally { if (active) busy.value = false }
}
function changeBoolean(event: Event, action: string, current: boolean) {
  // 以服务返回值确认选择；失败时不保留浏览器先行切换的勾选状态。
  if (event.currentTarget instanceof HTMLInputElement) event.currentTarget.checked = current
  void run(action, !current)
}
onMounted(() => { void run('load') })
onBeforeUnmount(() => { active = false })
defineExpose({ update })
</script>

<template>
  <section class="capture-settings" aria-labelledby="capture-settings-title" :aria-busy="busy">
    <header class="capture-settings-heading"><h2 id="capture-settings-title">采集与连接</h2><p>管理游戏连接与启动方式</p></header>
    <p v-if="error" class="capture-error" role="alert">{{ error }}。可重试，已有结果仍保留。</p>
    <div class="capture-connection" :class="{ 'needs-help': environmentNeedsHelp || capture?.status === 'error' }">
      <div class="capture-connection-main">
        <div class="capture-connection-copy"><span class="capture-connection-dot" aria-hidden="true"></span><div><h3>{{ summary.title }}</h3><p>{{ summary.message }}</p></div></div>
        <button class="primary-button small capture-primary" :disabled="busy || !data || (!data.running && environment?.actions.includes('install'))" @click="run(data?.running ? 'stop' : 'start')"><UiIcon :name="data?.running ? 'square' : 'player-play'" />{{ data?.running ? '停止采集' : '开始采集' }}</button>
      </div>
      <div class="capture-status-toolbar">
      <ol v-if="data" class="capture-stages" aria-label="连接状态">
        <li v-for="(stage, index) in stages" :key="stage.id" :class="{ 'is-ok': stage.check?.status === 'ok', 'is-warning': stage.check?.status === 'error' || stage.check?.status === 'warning' }"><UiIcon :name="stage.id === 'capture' && data?.running ? 'activity' : icon(stage.check)" /><span>{{ stage.label }}</span><UiIcon v-if="index < stages.length - 1" name="chevron-right" class="capture-stage-divider" /></li>
      </ol>
        <button class="capture-text-button capture-diagnostic-toggle" :aria-expanded="showDetails" aria-controls="capture-connection-details" @click="showDetails = !showDetails">{{ showDetails ? '收起诊断' : '查看诊断' }}<UiIcon :name="showDetails ? 'chevron-down' : 'chevron-right'" /></button>
      </div>
    <section v-if="showDetails" id="capture-connection-details" class="capture-details" aria-label="连接诊断">
      <div class="capture-detail-tools"><button class="ghost-button small" :disabled="busy" @click="run('load')">刷新状态</button><button class="ghost-button small" :disabled="busy || installing" @click="run('recheck')">重新检测环境</button></div>
      <p v-if="!data" role="status">{{ busy ? '正在加载诊断…' : '尚无诊断结果，请刷新状态。' }}</p>
      <div v-for="check in detailChecks" :key="check.id" class="capture-detail" :data-check="check.id">
        <strong>{{ check.title }}</strong><p>{{ check.message }}</p>
        <template v-if="check.id === 'environment'">
          <p v-if="data && data.install.phase !== 'idle'" role="status">{{ data.install.message }}</p>
          <progress v-if="installing" :value="data?.install.progress ?? undefined" max="1" aria-label="Npcap 安装进度"></progress>
          <p v-if="check.actions.includes('install')">安装时保留 WinPcap API-compatible Mode；安装器退出后自动检测。<a href="https://npcap.com/#download" target="_blank" rel="noreferrer">Npcap 官方下载页</a></p>
          <div v-if="check.actions.some(action => action === 'install' || action === 'rsc')" class="capture-detail-tools"><button v-for="action in check.actions.filter(action => action === 'install' || action === 'rsc')" :key="action" class="ghost-button small" :disabled="busy || installing" @click="run(action)">{{ labels[action] }}</button></div>
        </template>
      </div>
      <div class="capture-advanced">
        <strong>高级诊断</strong>
        <form class="capture-key-form" @submit.prevent="applyKey">
          <label for="capture-manual-key">手动密钥 <span class="capture-footnote">16 字节 ASCII 或 32 位 hex</span></label>
          <div class="capture-key-controls"><input id="capture-manual-key" v-model="keyText" type="text" autocomplete="off" :spellcheck="false" placeholder="粘贴密钥文本" :disabled="busy"><button type="submit" class="ghost-button small" :disabled="busy">应用密钥</button></div>
          <p v-if="keyMessage" class="capture-footnote" role="status">{{ keyMessage }}</p>
        </form>
        <template v-if="data">
          <p class="capture-footnote">累计观察：原始流 {{ data.totals.raw_chunks }} 段 / {{ data.totals.raw_bytes }} 字节；解密成功 {{ data.totals.decrypt_ok }}；解密失败 {{ data.totals.decrypt_fail }}；缺密钥 {{ data.totals.key_miss }}；解析失败 {{ data.totals.parse_fail }}；会话 {{ data.sessions.length }}</p>
          <p v-if="data.event_log_name" class="capture-footnote">事件日志：{{ data.event_log_name }}</p>
          <div class="capture-session-table"><table>
            <caption class="sr-only">采集会话</caption>
            <colgroup><col class="capture-session-id-col"><col><col></colgroup>
            <thead><tr><th scope="col">会话与账号</th><th scope="col">状态</th><th scope="col">解析</th></tr></thead>
            <tbody><tr v-for="session in data.sessions" :key="session.session_id">
              <td><strong>{{ session.name || '身份未确认' }}</strong><span v-if="session.uid !== '0'">UID {{ session.uid }}</span><span>{{ session.session_id }}</span></td>
              <td>{{ sessionLabels[session.status] || session.status }}<span>{{ session.has_key ? '已有密钥' : '未获取密钥' }}</span><span>最近 {{ activityTime(session.last_activity) }}</span></td>
              <td>成功 {{ session.decrypt_ok }} / {{ session.data_frames }}<span>失败 {{ session.failures }}</span></td>
            </tr><tr v-if="!data.sessions.length"><td colspan="3">暂无会话</td></tr></tbody>
          </table></div>
        </template>
      </div>
      <p class="capture-footnote">以上为累计观察，不代表当前连接健康或业务数据完整。</p>
      <p v-if="data?.automation.audit_guidance" class="capture-footnote">{{ data.automation.audit_guidance }}</p>
    </section>
      <div v-if="data" class="capture-behaviors">
        <div class="capture-behavior-group">
          <strong class="capture-behavior-title">启动选项</strong>
          <div class="capture-options">
            <label class="capture-option" :class="{ 'is-selected': data.autostart }" title="启动应用时自动开始采集"><input type="checkbox" :checked="data.autostart" :disabled="busy" @change="changeBoolean($event, 'autostart', data.autostart)"><span>打开即采集</span></label>
            <label class="capture-option" :class="{ 'is-selected': data.automation.enabled }" title="游戏启动时监听，关闭后退出"><input type="checkbox" :checked="data.automation.enabled" :disabled="busy" @change="changeBoolean($event, 'automation', data.automation.enabled)"><span>游戏启动跟随</span></label>
          </div>
          <p v-if="automationProgress" class="capture-behavior-note" role="status">{{ automationProgress }}</p>
          <p v-else class="capture-behavior-note">可独立启用；游戏跟随会在游戏关闭后退出。</p>
        </div>
        <div class="capture-behavior-group">
          <div class="capture-record-toolbar"><div class="capture-record-label"><strong class="capture-behavior-title">录制</strong><span class="capture-record-state" :class="{ 'is-recording': data.recording }">{{ data.recording ? '录制中' : '未录制' }}</span></div><button class="ghost-button small" :disabled="busy || !data.running" @click="run('recording', !data.recording)">{{ data.recording ? '停止录制' : '开始录制' }}</button></div>
          <div class="capture-options"><label class="capture-option" :class="{ 'is-selected': data.recording_requested }"><input type="checkbox" :checked="data.recording_requested" :disabled="busy" @change="changeBoolean($event, 'recording', data.recording_requested)"><span>启动时自动录制</span></label></div>
          <p class="capture-behavior-note">保存原始流；采集中修改会立即生效。</p>
        </div>
      </div>
    </div>


    <p v-if="warning" class="capture-notice" role="status">{{ warning.message }}</p>
    <template v-if="data">
      <div class="capture-setting-row capture-network-row">
        <div class="capture-setting-copy"><strong>抓包网卡</strong><span>下次启动采集时生效</span></div>
        <div class="capture-network-controls"><div class="capture-select-row"><select v-model="selected" aria-label="抓包网卡" :disabled="busy" @change="run('select')"><option value="">默认路由网卡</option><option v-if="missingSelected" :value="selected">{{ selected }}（当前配置，尚未枚举）</option><option v-for="iface in ifaces" :key="iface.name" :value="iface.name">{{ iface.description || iface.name }}</option></select><button class="ghost-button small" :disabled="busy" @click="run('ifaces')">刷新</button></div><span class="capture-port-note">监听端口 {{ ports }}</span><span v-if="selected" class="capture-port-note capture-selected-name">{{ selected }}</span></div>
      </div>
    </template>
    <div v-else class="capture-empty"><p role="status">{{ busy ? '正在加载采集设置…' : '尚无采集设置，请重试。' }}</p><button class="ghost-button small" :disabled="busy" @click="run('load')">重新加载</button></div>
  </section>
</template>

<style scoped>
.capture-settings { min-width: 0; font-size: var(--fs-sm); }
.capture-settings-heading { margin-bottom: var(--space-6); }
.capture-settings-heading h2 { margin: 0; font-size: var(--fs-lg); }
.capture-settings-heading p { margin: var(--space-1) 0 0; color: var(--muted); }
.capture-connection { padding: var(--space-6); background: var(--teal-soft); border: 1px solid var(--line-soft); border-radius: var(--radius-sm); }
.capture-connection.needs-help { background: var(--amber-soft); border-color: var(--amber); }
.capture-connection-main { display: flex; justify-content: space-between; align-items: flex-start; gap: var(--space-6); }
.capture-connection-copy { display: flex; gap: var(--space-4); min-width: 0; }
.capture-connection-copy > div { min-width: 0; }
.capture-connection-dot { width: 10px; height: 10px; flex: none; margin-top: var(--space-2); border-radius: 50%; background: var(--teal); }
.needs-help .capture-connection-dot { background: var(--amber-ink); }
.capture-connection h3 { margin: 0; font-size: var(--fs-md); }
.capture-connection p { margin: var(--space-1) 0 0; color: var(--ink-soft); line-height: 1.5; }
.capture-primary { flex: none; min-width: 104px; }
.capture-status-toolbar { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: var(--space-4); margin-top: var(--space-6); padding-top: var(--space-5); border-top: 1px solid var(--line); }
.capture-diagnostic-toggle { flex: none; margin-left: auto; }
.capture-stages { display: flex; flex-wrap: wrap; list-style: none; margin: 0; padding: 0; gap: var(--space-5) var(--space-7); }
.capture-stages li { display: flex; gap: var(--space-3); align-items: center; color: var(--muted); min-width: 0; }
.capture-stages .is-ok { color: var(--teal-dark); }
.capture-stages .is-warning { color: var(--amber-ink); }
.capture-stage-divider { margin-left: var(--space-6); color: var(--muted-2); }
.capture-text-button { display: inline-flex; align-items: center; justify-content: flex-end; gap: var(--space-1); padding: var(--space-2) 0; color: var(--teal-dark); background: none; font-size: var(--fs-sm); min-height: 30px; }
.capture-connection .ghost-button, .capture-diagnostic-toggle { background: var(--panel); border: 1px solid var(--teal); color: var(--teal-dark); border-radius: var(--radius-sm); padding-inline: var(--space-4); }
.capture-connection .ghost-button:hover:not(:disabled), .capture-diagnostic-toggle:hover { background: var(--teal-dark); border-color: var(--teal-dark); color: var(--panel); }
.capture-connection button:focus-visible { outline: 2px solid var(--focus-ring); outline-offset: 2px; }
.capture-setting-row { display: flex; justify-content: space-between; align-items: center; gap: var(--space-6); min-height: 58px; padding: var(--space-5) 0; border-top: 1px solid var(--line-soft); }
.capture-setting-row > strong, .capture-setting-copy strong { color: var(--ink-soft); font-size: var(--fs-sm); }
.capture-setting-copy { min-width: 0; display: grid; gap: var(--space-1); }
.capture-setting-copy span, .capture-port-note { color: var(--muted); font-size: var(--fs-xs); line-height: 1.5; }
.capture-behaviors { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 240px), 1fr)); gap: var(--space-7); margin-top: var(--space-6); padding-top: var(--space-6); border-top: 1px solid var(--line); }
.capture-behavior-group { min-width: 0; }
.capture-behavior-title { color: var(--ink-soft); font-size: var(--fs-sm); }
.capture-options { display: flex; flex-wrap: wrap; align-items: flex-start; gap: var(--space-3); margin-top: var(--space-4); }
.capture-option { display: inline-flex; align-items: center; min-height: 32px; min-width: 0; gap: var(--space-3); padding: var(--space-2) var(--space-4); border: 1px solid var(--teal); border-radius: var(--radius-sm); background: var(--panel); color: var(--ink-soft); cursor: pointer; }
.capture-option.is-selected { border-color: var(--teal); background: var(--panel); color: var(--teal-dark); }
.capture-option input { flex: none; width: 16px; height: 16px; margin: 0; accent-color: var(--teal); }
.capture-option:focus-within { outline: 2px solid var(--focus-ring); outline-offset: 2px; }
.capture-record-toolbar, .capture-record-label { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-3); }
.capture-record-toolbar { justify-content: space-between; min-height: 32px; }
.capture-behavior-group:first-child > .capture-behavior-title { display: flex; align-items: center; min-height: 32px; }
.capture-record-state { color: var(--muted); font-size: var(--fs-xs); }
.capture-record-state.is-recording { color: var(--teal-dark); }
.capture-connection .capture-behavior-note { margin-top: var(--space-3); color: var(--muted); font-size: var(--fs-xs); }
.capture-network-row { align-items: flex-start; }
.capture-network-controls { width: min(360px, 58%); min-width: 0; display: grid; gap: var(--space-2); }
.capture-select-row { display: flex; gap: var(--space-3); min-width: 0; }
.capture-select-row select { flex: 1; min-width: 0; width: 100%; height: 32px; padding-inline: var(--space-4); border: 1px solid var(--line); border-radius: var(--radius-sm); background: var(--panel); font-size: var(--fs-sm); }
.capture-select-row button { flex: none; }
.capture-port-note { text-align: right; }
.capture-details { margin-top: var(--space-5); padding: var(--space-5) 0 0; border-top: 1px solid var(--line-soft); }
.capture-detail { padding-top: var(--space-4); }
.capture-detail p, .capture-footnote { margin: var(--space-2) 0 0; line-height: 1.5; color: var(--muted); }
.capture-advanced { margin-top: var(--space-6); padding-top: var(--space-5); border-top: 1px solid var(--line); }
.capture-key-form { display: grid; gap: var(--space-3); margin-top: var(--space-4); }
.capture-key-form label { overflow-wrap: anywhere; }
.capture-key-controls { display: flex; flex-wrap: wrap; gap: var(--space-3); }
.capture-key-controls input { flex: 1 1 160px; min-width: 0; width: 100%; height: 32px; border: 1px solid var(--line); border-radius: var(--radius-sm); background: var(--panel); padding-inline: var(--space-3); font-size: var(--fs-sm); }
.capture-session-table { max-height: 240px; overflow-y: auto; margin-top: var(--space-4); }
.capture-session-table table { width: 100%; table-layout: fixed; border-collapse: collapse; font-size: var(--fs-xs); text-align: left; }
.capture-session-table th, .capture-session-table td { padding: var(--space-3); border-bottom: 1px solid var(--line); overflow-wrap: anywhere; }
.capture-session-id-col { width: 44%; }
.capture-session-table td span { display: block; color: var(--muted); margin-top: var(--space-1); }
.capture-session-table td { vertical-align: top; }
.capture-detail strong { font-size: var(--fs-xs); }
.capture-detail-tools { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-3); margin-top: var(--space-3); }
.capture-footnote { font-size: var(--fs-xs); }
.capture-details progress { width: 100%; max-width: 24rem; margin-top: var(--space-3); }
.capture-error, .capture-notice { margin: 0 0 var(--space-5); padding: var(--space-4); border-radius: var(--radius-sm); line-height: 1.5; }
.capture-error { color: var(--danger-ink); background: var(--danger-soft); }
.capture-notice { color: var(--amber-ink); background: var(--amber-soft); }
.capture-empty { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-4); }
.capture-settings p, .capture-settings strong, .capture-settings span { overflow-wrap: anywhere; }
.capture-settings button { white-space: normal; height: auto; min-height: 32px; padding-block: var(--space-2); }
.capture-settings .ui-icon { flex: none; }
@media (max-width: 760px) {
  .capture-connection-main { flex-wrap: wrap; gap: var(--space-4); }
  .capture-primary { margin-left: auto; }
  .capture-stages { gap: var(--space-4); }
  .capture-stage-divider { display: none; }
  .capture-network-row { flex-direction: column; gap: var(--space-4); }
  .capture-network-controls { width: 100%; }
  .capture-port-note { text-align: left; }
}
@media (max-width: 480px) {
  .capture-connection { padding: var(--space-4); }
  .capture-session-id-col { width: 40%; }
  .capture-session-table th, .capture-session-table td { padding: var(--space-2); }
}
</style>
