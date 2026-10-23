<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { parseCaptureDiagnostics, parseIfaces } from '../types/captureDiagnostics'
import type { CaptureDiagnostics, CaptureDiagnosticsHost } from '../types/captureDiagnostics'
const props = defineProps<{ host: CaptureDiagnosticsHost }>()
const data = ref<CaptureDiagnostics | null>(null)
const error = ref(''), busy = ref(false), selected = ref('')
const ifaces = ref<{ name: string; description: string }[]>([])
let active = true
const labels: Record<string, string> = { recheck: '重新检测环境', install: '一键安装 Npcap', rsc: '禁用 RSC', ifaces: '刷新网卡', start: '开始采集', stop: '停止采集', advanced: '打开高级诊断' }
const statuses = { ok: '已观察', error: '需处理', warning: '注意', info: '配置', idle: '未启动', waiting: '等待' }
const installing = computed(() => data.value && !['idle', 'completed', 'failed'].includes(data.value.install.phase))
const missingSelected = computed(() => selected.value && !ifaces.value.some(row => row.name === selected.value))
function update(value: unknown) {
  if (!active) return
  try { data.value = parseCaptureDiagnostics(value); selected.value = data.value.iface; return true }
  catch (e) { error.value = e instanceof Error ? e.message : String(e) }
}
async function run(action: string) {
  if (busy.value || !active) return
  if (action === 'advanced') { props.host.advanced(); return }
  busy.value = true; error.value = ''
  try {
    if (action === 'ifaces') {
      const result = await props.host.request('/api/capture/ifaces')
      if (active) ifaces.value = parseIfaces(result)
    } else {
      const paths: Record<string, string> = { load: '', recheck: '/environment', install: '/npcap/install', rsc: '/rsc', start: '/start', stop: '/stop', select: '/iface' }
      const result = await props.host.request('/api/capture' + paths[action], action === 'load' ? undefined : {
        method: 'POST', ...(action === 'select' ? { body: { name: selected.value } } : {}),
      })
      if (active && update(result)) props.host.publish(result)
    }
  } catch (e) {
    if (active) { error.value = e instanceof Error ? e.message : String(e); selected.value = data.value?.iface ?? '' }
  } finally { if (active) busy.value = false }
}
onMounted(() => { void run('load') })
onBeforeUnmount(() => { active = false })
defineExpose({ update })
</script>

<template>
  <section class="capture-guide" aria-labelledby="capture-guide-title" :aria-busy="busy">
    <div class="capture-guide-heading"><h2 id="capture-guide-title">采集向导与健康诊断</h2><button class="ghost-button small" :disabled="busy" @click="run('load')">{{ busy ? '处理中…' : '刷新状态' }}</button></div>
    <p class="muted">按顺序检查环境、网卡、采集和解密。所有计数为累计观察，不代表当前连接健康或业务数据完整。</p>
    <p v-if="error" class="capture-guide-error" role="alert">{{ error }}。可重试；已有结果仍保留。</p>
    <p v-if="!data" role="status">{{ busy ? '正在加载诊断…' : '尚无诊断结果，请刷新状态。' }}</p>
    <ol v-else class="capture-guide-list">
      <li v-for="check in data.diagnostics" :key="check.id" class="capture-guide-check" :data-check="check.id">
        <div class="capture-guide-heading"><h3>{{ check.title }}</h3><span class="status-pill" :class="{ ok: check.status === 'ok', warn: check.status === 'warning', bad: check.status === 'error' }">{{ statuses[check.status] }}</span></div>
        <p>{{ check.message }}</p>
        <template v-if="check.id === 'environment' && data.install.phase !== 'idle'">
          <p role="status">{{ data.install.message }}</p>
          <progress v-if="installing" :value="data.install.progress ?? undefined" max="1" aria-label="Npcap 安装进度"></progress>
        </template>
        <p v-if="check.id === 'environment'" class="muted">安装时保留 WinPcap API-compatible Mode；安装器退出后自动检测。<a href="https://npcap.com/#download" target="_blank" rel="noreferrer">Npcap 官方下载页</a></p>
        <label v-if="check.id === 'network'" class="capture-guide-iface field">下次启动使用的网卡
          <select v-model="selected" :disabled="busy" @change="run('select')">
            <option value="">默认路由网卡</option>
            <option v-if="missingSelected" :value="selected">{{ selected }}（当前配置，尚未枚举）</option>
            <option v-for="iface in ifaces" :key="iface.name" :value="iface.name">{{ iface.description || iface.name }}</option>
          </select>
        </label>
        <div class="capture-guide-actions"><button v-for="action in check.actions" :key="action" class="ghost-button small" :disabled="busy || (!!installing && ['install', 'rsc', 'recheck'].includes(action))" @click="run(action)">{{ labels[action] }}</button></div>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.capture-guide { min-width: 0; padding-block: var(--space-6); }
.capture-guide-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-4); flex-wrap: wrap; }
.capture-guide h2, .capture-guide h3 { margin: 0; font-size: var(--fs-md); }
.capture-guide p { margin-block: var(--space-4); overflow-wrap: anywhere; }
.capture-guide-list { list-style: none; padding: 0; margin: var(--space-6) 0 0; display: grid; gap: var(--space-5); }
.capture-guide-check { min-width: 0; padding: var(--space-6); border: 1px solid var(--line); border-radius: var(--radius-md); background: var(--surface-1); }
.capture-guide-actions { display: flex; flex-wrap: wrap; gap: var(--space-4); margin-top: var(--space-5); }
.capture-guide-error { color: var(--negative); }
.capture-guide-iface { display: grid; gap: var(--space-3); min-width: 0; }
.capture-guide select { width: 100%; min-width: 0; max-width: 100%; }
.capture-guide-heading > button { min-width: 7em; }
.capture-guide button { white-space: normal; height: auto; min-height: 30px; padding-block: var(--space-2); }
.capture-guide progress { width: 100%; max-width: 24rem; }
</style>
