<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import type { ApiClient } from '../api/client'
import { useColors } from '../composables/useColors'
import { matrixKey } from '../types/colors'
import ColorCardFace from '../components/ColorCardFace.vue'
import UiIcon from '../components/UiIcon.vue'
const props = defineProps<{ api: ApiClient; active: boolean }>()
const { data, loading, error, matrixRows, metaText, load, pause, resume, resetAccount } = useColors(props.api)
const failed = ref(new Set<string>())
const selectedKey = ref('')
const failedKey = (gid: number | string) => String(gid)
function failedIcon(gid: number | string) { failed.value.add(failedKey(gid)) }
function selectCell(key: string, state: string) {
  if (state !== 'empty') selectedKey.value = selectedKey.value === key ? '' : key
}
const selectedCell = computed(() => {
  if (!selectedKey.value) return null
  const [baseName, mixName] = selectedKey.value.split('|')
  const row = matrixRows.value.find(item => item.mix.name === mixName)
  const index = row?.cells.findIndex((_, cellIndex) => data.value?.base_axis[cellIndex]?.name === baseName) ?? -1
  const cell = index >= 0 ? row?.cells[index] : undefined
  return row && cell ? { baseName, mixName, cell } : null
})
function resetColorsAccount() { selectedKey.value = ''; resetAccount() }
defineExpose({ load, pause, resume, resetAccount: resetColorsAccount, error })
// 外壳挂载后把 active 由 false 翻到 true，首次加载靠这条 watch 触发。
watch(() => props.active, value => { if (value) void resume(); else pause() }, { flush: 'sync' })
onMounted(() => { if (props.active) void resume(); else pause() })
</script>
<template>
  <div class="stack colors-page" data-vue-page :aria-busy="loading">
    <section class="panel colors-matrix-panel">
      <div class="panel-head colors-head">
        <div class="colors-heading"><h2>色卡矩阵</h2><p>底色 × 混色 · 点击有卡格查看状态</p></div>
        <span id="cl-meta" class="colors-meta">{{ metaText }}</span>
      </div>
      <div class="colors-legend" aria-label="色卡状态说明">
        <span><i class="legend-dot legend-dot--empty"></i>目录无卡</span>
        <span><i class="legend-dot legend-dot--catalog"></i>目录有卡</span>
        <span><i class="legend-dot legend-dot--owned"></i>当前账号持有</span>
        <small>窄窗口可横向滚动矩阵</small>
      </div>
      <div class="table-wrap">
        <div v-if="selectedCell" class="colors-selection" role="status">
          <div><b>{{ selectedCell.baseName }}底色 × {{ selectedCell.mixName }}混色</b><span v-if="selectedCell.cell.state === 'pets'">{{ selectedCell.cell.cell?.names || '当前账号已持有' }} · {{ selectedCell.cell.pets.length }} 只持有者</span><span v-else>目录已收录，当前账号尚未持有</span></div>
          <button type="button" class="ghost-button small" @click="selectedKey = ''">收起</button>
        </div>
        <div id="cl-matrix" class="mm-matrix">
          <table>
            <thead>
              <tr>
                <th class="mm-corner">混色 \ 底色</th>
                <th v-for="base in data?.base_axis || []" :key="base.name"><i v-if="base.hex" class="swatch" :style="{ background: base.hex }"></i>{{ base.name }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in matrixRows" :key="row.mix.name">
                <th class="mm-rowhead"><i v-if="row.mix.hex" class="swatch" :style="{ background: row.mix.hex }"></i><b>{{ row.mix.name }}</b></th>
                <td v-for="(cell, index) in row.cells" :key="index" class="mm-cell" :class="{ empty: cell.state === 'empty', selected: selectedKey === matrixKey(data?.base_axis[index]?.name || '', row.mix.name) }" :data-state="cell.state" :data-mmkey="encodeURIComponent(matrixKey(data?.base_axis[index]?.name || '', row.mix.name))" :tabindex="cell.state === 'empty' ? undefined : 0" :aria-label="`${data?.base_axis[index]?.name || ''}底色与${row.mix.name}混色`" @click="selectCell(matrixKey(data?.base_axis[index]?.name || '', row.mix.name), cell.state)" @keydown.enter.prevent="selectCell(matrixKey(data?.base_axis[index]?.name || '', row.mix.name), cell.state)">
                  <template v-if="cell.state === 'empty'">—</template>
                  <template v-else-if="cell.state === 'card'">
                    <b class="cc-label" :title="cell.cell.names">{{ cell.cell.label }}</b>
                    <small class="cc-names">{{ cell.cell.names }}</small>
                    <span class="pet-color-card" role="img" :aria-label="cell.cell.names" :title="cell.cell.names"><ColorCardFace :card-id="cell.cell.card_id" :base-color="cell.cell.base_color" :mix-color="cell.cell.mix_color" /></span>
                  </template>
                  <template v-else>
                    <span v-for="pet in cell.pets" :key="pet.gid" class="mm-pet" :data-mm="pet.gid">
                      <img v-if="pet.icon_url && !failed.has(failedKey(pet.gid))" :src="pet.icon_url" alt="" loading="eager" decoding="async" @error="failedIcon(pet.gid)">
                      <UiIcon :name="pet.gender === 2 ? 'gender-female' : 'gender-male'" />{{ pet.name }}<small>Lv{{ pet.level }}</small>
                    </span>
                    <span v-for="pet in cell.pets" :key="`card-${pet.gid}`" v-show="pet.color_card" class="pet-color-card" role="img" :aria-label="`${pet.color_card?.name} · ${pet.color_card?.particle_name}`" :title="`${pet.color_card?.name} · ${pet.color_card?.particle_name}`"><ColorCardFace :card-id="pet.color_card?.card_id || ''" :base-color="pet.color_card?.base_color || ''" :mix-color="pet.color_card?.mix_color || ''" :particle-id="pet.color_card?.particle_id" /></span>
                  </template>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="loading && !data" class="empty-hint" role="status"><UiIcon name="clock" />正在加载色卡…</div>
        <div v-else-if="error" class="empty-hint" role="alert">色卡加载失败：{{ error }}<div class="button-row"><button class="ghost-button" @click="load">重试</button></div></div>
        <div v-else id="cl-empty" class="empty-hint" v-show="(data?.pet_total || 0) === 0">宠物库中没有带色卡的宠物</div>
      </div>
    </section>
    <div class="overview-lower colors-lower">
      <section class="panel">
        <div class="panel-head"><h2>赛季卡</h2><span id="cl-seasonal-count" class="muted">{{ data ? data.seasonal.length + ' 只' : '' }}</span></div>
        <div id="cl-seasonal" class="bl-chips">
          <span v-for="pet in data?.seasonal || []" :key="pet.gid" class="mm-pet" :data-mm="pet.gid">
            <img v-if="pet.icon_url && !failed.has(failedKey(pet.gid))" :src="pet.icon_url" alt="" loading="eager" decoding="async" @error="failedIcon(pet.gid)">
            <UiIcon :name="pet.gender === 2 ? 'gender-female' : 'gender-male'" />{{ pet.name }}<small>Lv{{ pet.level }}</small>
            <span v-if="pet.color_card" class="pet-color-card" role="img" :aria-label="`${pet.color_card.name} · ${pet.color_card.particle_name}`" :title="`${pet.color_card.name} · ${pet.color_card.particle_name}`"><ColorCardFace :card-id="pet.color_card.card_id" :base-color="pet.color_card.base_color" :mix-color="pet.color_card.mix_color" :particle-id="pet.color_card.particle_id" /></span>
          </span>
        </div>
        <div id="cl-seasonal-empty" class="empty-hint" v-show="!!data && !data.seasonal.length">暂无赛季卡</div>
      </section>
      <section class="panel">
        <div class="panel-head"><h2>未收录编号</h2><span id="cl-unknown-count" class="muted">{{ data ? data.unknown.length + ' 只' : '' }}</span></div>
        <div id="cl-unknown" class="bl-chips">
          <span v-for="pet in data?.unknown || []" :key="pet.gid" class="mm-pet" :data-mm="pet.gid">
            <img v-if="pet.icon_url && !failed.has(failedKey(pet.gid))" :src="pet.icon_url" alt="" loading="eager" decoding="async" @error="failedIcon(pet.gid)">
            <UiIcon :name="pet.gender === 2 ? 'gender-female' : 'gender-male'" />{{ pet.name }}<small>Lv{{ pet.level }}</small>
            <span v-if="pet.card_id" class="muted">#{{ pet.card_id }}</span>
            <span v-else class="muted">编号未解析</span>
          </span>
        </div>
        <div id="cl-unknown-empty" class="empty-hint" v-show="!!data && !data.unknown.length">全部色卡都已收录</div>
      </section>
    </div>
  </div>
</template>
<style scoped>
.colors-page {
  max-width: none;
  height: 100%;
  min-height: 0;
  overflow: auto;
  padding: var(--space-4);
}
.colors-page .panel { margin-bottom: var(--space-5); box-shadow: none; }
.colors-matrix-panel { padding: 0; overflow: hidden; }
.colors-head { align-items: center; justify-content: space-between; gap: var(--space-5); margin: 0; padding: var(--space-5) var(--space-6); border-bottom: 1px solid var(--line-soft); }
.colors-heading { min-width: 0; }
.colors-heading h2 { font-size: var(--fs-xl); }
.colors-heading p { margin: var(--space-1) 0 0; color: var(--muted); font-size: var(--fs-xs); }
.colors-meta { flex: none; padding: var(--space-2) var(--space-4); border: 1px solid var(--line-soft); border-radius: 999px; background: var(--teal-soft); color: var(--teal-dark); font-size: var(--fs-xs); font-weight: 700; }
.colors-legend { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-4); padding: var(--space-3) var(--space-6); border-bottom: 1px solid var(--line-soft); color: var(--muted); font-size: var(--fs-2xs); }
.colors-legend span { display: inline-flex; align-items: center; gap: var(--space-2); }
.colors-legend small { margin-left: auto; color: var(--muted-2); font-size: var(--fs-3xs); }
.legend-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--line); }
.legend-dot--catalog { background: var(--amber); }
.legend-dot--owned { background: var(--teal); }
.colors-matrix-panel > .table-wrap { max-height: calc(100vh - var(--topbar) - 198px); margin: 0; padding: 0 var(--space-4) var(--space-4); }
#cl-matrix { overflow: auto; border: 1px solid var(--line-soft); border-radius: var(--radius-md); background: var(--surface-1); }
#cl-matrix .mm-matrix { min-width: 920px; }
#cl-matrix .mm-matrix table { width: 100%; border-collapse: separate; border-spacing: 0; }
#cl-matrix .mm-matrix th, #cl-matrix .mm-matrix td { min-width: 118px; padding: var(--space-3); border-right: 1px solid var(--line-soft); border-bottom: 1px solid var(--line-soft); }
#cl-matrix .mm-matrix thead th { position: sticky; top: 0; z-index: 3; height: 38px; background: var(--teal-soft); color: var(--ink-soft); font-size: var(--fs-xs); }
#cl-matrix .mm-matrix thead th:last-child, #cl-matrix .mm-matrix tbody td:last-child { border-right: 0; }
#cl-matrix .mm-matrix tbody tr:last-child th, #cl-matrix .mm-matrix tbody tr:last-child td { border-bottom: 0; }
#cl-matrix .mm-corner { position: sticky; left: 0; z-index: 5; min-width: 118px; background: var(--teal-soft); }
#cl-matrix .mm-rowhead { position: sticky; left: 0; z-index: 2; min-width: 118px; background: var(--surface-2); }
#cl-matrix .mm-cell { min-height: 96px; vertical-align: middle; background: var(--panel); transition: background-color var(--motion-fast), box-shadow var(--motion-fast); }
#cl-matrix .mm-cell[data-state="card"] { background: color-mix(in srgb, var(--amber-soft) 18%, var(--panel)); }
#cl-matrix .mm-cell[data-state="pets"] { background: color-mix(in srgb, var(--teal-soft) 24%, var(--panel)); }
#cl-matrix .mm-cell:hover, #cl-matrix .mm-cell:focus-visible { background: var(--teal-soft); }
#cl-matrix .mm-cell:focus-visible { outline: 2px solid var(--teal); outline-offset: -2px; }
#cl-matrix .mm-cell.selected { outline: 2px solid var(--teal); outline-offset: -2px; box-shadow: inset 4px 0 0 var(--teal); }
#cl-matrix .mm-cell.empty { color: var(--muted-2); background: var(--surface-1); }
#cl-matrix .cc-label { display: block; font-size: var(--fs-sm); }
#cl-matrix .cc-names { display: block; max-width: 100%; margin-top: var(--space-1); overflow: hidden; color: var(--muted); font-size: var(--fs-2xs); text-overflow: ellipsis; white-space: nowrap; }
#cl-matrix .pet-color-card { width: 72px; height: 42px; margin: var(--space-3) auto var(--space-1); border-radius: var(--radius-md); box-shadow: 0 2px 8px color-mix(in srgb, var(--ink) 12%, transparent); }
#cl-matrix .mm-pet { max-width: 100%; margin: var(--space-1) 0; }
.colors-selection { display: flex; align-items: center; justify-content: space-between; gap: var(--space-4); margin-top: var(--space-3); padding: var(--space-3) var(--space-4); border: 1px solid var(--teal); border-radius: var(--radius-md); background: var(--teal-soft); color: var(--ink-soft); font-size: var(--fs-xs); }
.colors-selection div { min-width: 0; display: flex; align-items: baseline; flex-wrap: wrap; gap: var(--space-3); }
.colors-selection span { color: var(--muted); }
.colors-selection button { flex: none; }
.colors-lower { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
.colors-lower .panel { padding: var(--space-5); }
.colors-lower .panel-head { align-items: center; }
.colors-lower .panel-head h2 { font-size: var(--fs-md); }
@media (max-width: 960px) {
  .colors-page { padding: var(--space-3); }
  .colors-head { align-items: flex-start; flex-direction: column; padding: var(--space-4); }
  .colors-meta { max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .colors-legend { padding: var(--space-3) var(--space-4); }
  .colors-legend small { width: 100%; margin-left: 0; }
  .colors-matrix-panel > .table-wrap { max-height: none; padding: 0 var(--space-3) var(--space-3); }
  .colors-selection { align-items: flex-start; }
  .colors-lower { grid-template-columns: minmax(0, 1fr); }
}
</style>
