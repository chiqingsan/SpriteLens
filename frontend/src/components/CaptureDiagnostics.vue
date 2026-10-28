<script setup lang="ts">
import UiSelect from './UiSelect.vue'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import UiIcon from './UiIcon.vue'
import UiSelect from './UiSelect.vue'
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
const ifaceOptions = computed(() => [
  { value: '', label: '默认路由网卡' },
  ...(missingSelected.value ? [{ value: selected.value, label: String(selected.value) + '（当前配置，尚未枚举）' }] : []),
  ...ifaces.value.map(row => ({ value: row.name, label: row.description || row.name })),
])
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
function pickIface(value: string | number | null) {
  selected.value = String(value ?? '')
  void run('select')
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
        <div class="capture-network-controls"><div class="capture-select-row"><UiSelect size="sm" :options="ifaceOptions" :model-value="selected" label="抓包网卡" placeholder="默认路由网卡" :disabled="busy" @change="pickIface" /><button class="ghost-button small" :disabled="busy" @click="run('ifaces')">刷新</button></div><span class="capture-port-note">监听端口 {{ ports }}</span><span v-if="selected" class="capture-port-note capture-selected-name">{{ selected }}</span></div>
      </div>
    </template>
    <div v-else class="capture-empty"><p role="status">{{ busy ? '正在加载采集设置…' : '尚无采集设置，请重试。' }}</p><button class="ghost-button small" :disabled="busy" @click="run('load')">重新加载</button></div>
  </section>
</template>

<style scoped>
/* 采集与连接：设置页内的一块，用一张浅绿连接卡承载状态、步骤和启动选项。 */
.capture-settings { min-width: 0; color: var(--ink); font-size: var(--fs-sm); }
.capture-settings-heading { margin-bottom: var(--space-4); }
.capture-settings-heading h2 { margin: 0; font-size: var(--fs-lg); font-weight: 600; line-height: 1.3; }
.capture-settings-heading p { margin: var(--space-1) 0 0; color: var(--muted); font-size: var(--fs-2xs); line-height: 1.5; }
.capture-error, .capture-notice { margin: 0 0 var(--space-4); padding: var(--space-3) var(--space-4); border-radius: var(--radius-md); font-size: var(--fs-xs); line-height: 1.5; overflow-wrap: anywhere; }
.capture-error { border: 1px solid color-mix(in srgb, var(--danger) 26%, transparent); background: var(--danger-soft); color: var(--danger-ink); }
.capture-notice { border: 1px solid var(--amber-line); background: var(--amber-soft); color: var(--amber-ink); }

/* 采集与连接：设置页内的一块。中性表面 + 一枚状态点表达“在/不在采集”，
   不再用大面积主题色铺底，把强调色留给状态点与主操作。 */
.capture-connection { padding: var(--space-5) var(--space-6); border: 1px solid color-mix(in srgb, var(--teal) 14%, var(--line-soft)); border-radius: var(--radius-lg); background: color-mix(in srgb, var(--teal-soft) 24%, var(--panel)); }
.capture-connection.needs-help { border-color: color-mix(in srgb, var(--amber) 40%, var(--line-soft)); background: color-mix(in srgb, var(--amber-soft) 30%, var(--panel)); }
.capture-connection-main { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-5); }
.capture-connection-copy { display: flex; gap: var(--space-3); min-width: 0; }
.capture-connection-copy > div { min-width: 0; }
.capture-connection-dot { width: 8px; height: 8px; flex: none; margin-top: 7px; border-radius: 50%; background: var(--teal); box-shadow: 0 0 0 4px color-mix(in srgb, var(--teal) 16%, transparent); }
.needs-help .capture-connection-dot { background: var(--amber); box-shadow: 0 0 0 4px color-mix(in srgb, var(--amber) 18%, transparent); }
.capture-connection h3 { margin: 0; color: var(--ink); font-size: var(--fs-md); font-weight: 600; line-height: 1.35; }
.capture-connection p { margin: var(--space-1) 0 0; color: var(--ink-soft); font-size: var(--fs-xs); line-height: 1.5; overflow-wrap: anywhere; }
.capture-primary { flex: none; min-width: 104px; }
.capture-status-toolbar { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: var(--space-3); margin-top: var(--space-4); padding-top: var(--space-4); border-top: 1px solid var(--line-soft); }
.capture-diagnostic-toggle { flex: none; margin-left: auto; }
.capture-connection button:focus-visible { outline: 2px solid var(--focus-ring); outline-offset: 2px; }

.capture-stages { display: flex; flex-wrap: wrap; gap: var(--space-2) var(--space-6); margin: 0; padding: 0; list-style: none; }
.capture-stages li { position: relative; display: flex; align-items: center; gap: var(--space-2); height: 28px; padding: 0 var(--space-3); border: 1px solid var(--line-soft); border-radius: 999px; background: color-mix(in srgb, var(--panel) 82%, transparent); color: var(--ink-soft); font-size: var(--fs-2xs); white-space: nowrap; }
.capture-stages li .ui-icon { width: 14px; height: 14px; flex: none; color: var(--muted); }
.capture-stages .is-ok { border-color: color-mix(in srgb, var(--teal) 30%, transparent); color: var(--teal-dark); }
.capture-stages .is-ok .ui-icon { color: var(--teal); }
.capture-stages .is-warning { border-color: color-mix(in srgb, var(--amber) 40%, transparent); background: color-mix(in srgb, var(--amber-soft) 80%, transparent); color: var(--amber-ink); }
.capture-stages .is-warning .ui-icon { color: var(--amber-ink); }
.capture-stage-divider { position: absolute; left: 100%; width: 12px; height: 12px; margin-left: 2px; color: var(--muted-2); }
.capture-text-button { display: inline-flex; align-items: center; justify-content: flex-end; gap: var(--space-1); min-height: 30px; padding: var(--space-1) var(--space-2); border: 0; border-radius: var(--radius-sm); background: transparent; color: var(--teal-dark); font-size: var(--fs-xs); font-weight: 500; }
.capture-text-button:hover { background: color-mix(in srgb, var(--panel) 72%, transparent); }
.capture-details { margin-top: var(--space-3); padding: var(--space-4); border: 1px solid var(--line-soft); border-radius: var(--radius-md); background: var(--surface-1); }
.capture-detail-tools { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2); margin-top: var(--space-2); }
.capture-detail { padding-top: var(--space-3); }
.capture-detail strong { color: var(--ink-soft); font-size: var(--fs-xs); font-weight: 600; }
.capture-detail p { margin: var(--space-1) 0 0; color: var(--muted); font-size: var(--fs-2xs); line-height: 1.5; overflow-wrap: anywhere; }
.capture-advanced { margin-top: var(--space-4); padding-top: var(--space-4); border-top: 1px solid var(--line-soft); }
.capture-advanced > strong { color: var(--ink-soft); font-size: var(--fs-xs); font-weight: 600; }
.capture-key-form { display: grid; gap: var(--space-2); margin-top: var(--space-2); }
.capture-key-form label { color: var(--ink-soft); font-size: var(--fs-2xs); overflow-wrap: anywhere; }
.capture-key-controls { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2); }
.capture-key-controls input { flex: 1 1 160px; min-width: 0; height: 32px; padding: 0 var(--space-3); border: 1px solid var(--line); border-radius: var(--radius-sm); background: var(--panel); color: var(--ink); font-size: var(--fs-xs); }
.capture-footnote { margin: var(--space-1) 0 0; color: var(--muted); font-size: var(--fs-2xs); line-height: 1.5; overflow-wrap: anywhere; }
.capture-session-table { max-height: 240px; margin-top: var(--space-3); overflow: auto; border: 1px solid var(--line-soft); border-radius: var(--radius-sm); }
.capture-session-table table { width: 100%; border-collapse: collapse; table-layout: fixed; font-size: var(--fs-3xs); text-align: left; }
.capture-session-table th { position: sticky; top: 0; z-index: 1; padding: var(--space-2) var(--space-3); border-bottom: 1px solid var(--line-soft); background: var(--surface-1); color: var(--muted); font-weight: 600; }
.capture-session-table td { padding: var(--space-2) var(--space-3); border-bottom: 1px solid var(--line-soft); overflow-wrap: anywhere; vertical-align: top; }
.capture-session-table tbody tr:last-child td { border-bottom: 0; }
.capture-session-table tbody tr:hover td { background: var(--surface-1); }
.capture-session-table td span { display: block; margin-top: 1px; color: var(--muted); }
.capture-session-id-col { width: 44%; }
.capture-details progress { width: 100%; max-width: 24rem; margin-top: var(--space-2); accent-color: var(--teal); }

.capture-behaviors { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 240px), 1fr)); gap: var(--space-5); margin-top: var(--space-4); padding-top: var(--space-4); border-top: 1px solid var(--line-soft); }
.capture-behavior-group { min-width: 0; }
.capture-behavior-title { color: var(--ink-soft); font-size: var(--fs-xs); font-weight: 600; }
.capture-options { display: flex; flex-wrap: wrap; align-items: flex-start; gap: var(--space-2); margin-top: var(--space-3); }
.capture-option { display: inline-flex; align-items: center; gap: var(--space-2); min-height: 30px; min-width: 0; padding: var(--space-1) var(--space-3); border: 1px solid var(--line); border-radius: 999px; background: color-mix(in srgb, var(--panel) 72%, transparent); color: var(--ink-soft); font-size: var(--fs-xs); cursor: pointer; }
.capture-option:hover { border-color: var(--teal); }
.capture-option.is-selected { border-color: var(--teal); background: var(--panel); color: var(--teal-dark); font-weight: 500; box-shadow: 0 1px 2px color-mix(in srgb, var(--teal) 16%, transparent); }
.capture-option input { flex: none; width: 16px; height: 16px; margin: 0; }
.capture-option:focus-within { outline: 2px solid var(--focus-ring); outline-offset: 2px; }
.capture-record-toolbar { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: var(--space-2); min-height: 30px; }
.capture-record-label { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2); }
.capture-record-state { display: inline-flex; align-items: center; gap: var(--space-1); padding: 1px var(--space-2); border-radius: 999px; background: color-mix(in srgb, var(--panel) 70%, transparent); color: var(--muted); font-size: var(--fs-3xs); }
.capture-record-state.is-recording { background: var(--danger-soft); color: var(--danger-ink); }
.capture-record-state.is-recording::before { content: ''; width: 6px; height: 6px; border-radius: 50%; background: var(--danger); }
.capture-behavior-note { margin: var(--space-2) 0 0; color: var(--ink-soft); font-size: var(--fs-3xs); line-height: 1.5; opacity: .88; overflow-wrap: anywhere; }

.capture-setting-row { display: flex; align-items: center; justify-content: space-between; gap: var(--space-5); min-height: 56px; padding: var(--space-4) 0; border-top: 1px solid var(--line-soft); }
.capture-setting-copy { display: grid; gap: var(--space-1); min-width: 0; }
.capture-setting-copy strong { color: var(--ink-soft); font-size: var(--fs-sm); font-weight: 500; }
.capture-setting-copy span { color: var(--muted); font-size: var(--fs-2xs); line-height: 1.5; }
.capture-network-row { align-items: flex-start; }
.capture-network-controls { display: grid; gap: var(--space-2); width: min(360px, 58%); min-width: 0; }
.capture-select-row { display: flex; gap: var(--space-2); min-width: 0; }
.capture-select-row .ui-picker { flex: 1; width: 100%; min-width: 0; font-size: var(--fs-xs); }
.capture-select-row button { flex: none; }
.capture-port-note { color: var(--muted); font-size: var(--fs-2xs); line-height: 1.5; text-align: right; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.capture-selected-name { overflow-wrap: anywhere; }
.capture-empty { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-3); padding: var(--space-4); border: 1px dashed var(--line); border-radius: var(--radius-md); color: var(--muted); }
.capture-empty p { margin: 0; font-size: var(--fs-xs); }

@media (max-width: 760px) {
  .capture-connection { padding: var(--space-4); }
  .capture-connection-main { flex-direction: column; }
  .capture-primary { align-self: flex-start; }
  .capture-stages { gap: var(--space-2); }
  .capture-stage-divider { display: none; }
  .capture-setting-row { flex-direction: column; align-items: stretch; gap: var(--space-2); }
  .capture-network-controls { width: 100%; }
  .capture-port-note { text-align: left; }
}
@media (max-width: 480px) {
  .capture-behaviors { grid-template-columns: minmax(0, 1fr); }
  .capture-option { width: 100%; }
}
</style>
