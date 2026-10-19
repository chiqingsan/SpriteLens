<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import type { ApiClient } from '../api/client'
import { useColors } from '../composables/useColors'
import ColorCardFace from '../components/ColorCardFace.vue'
import UiIcon from '../components/UiIcon.vue'
const props = defineProps<{ api: ApiClient; active: boolean }>()
const { data, loading, error, matrixRows, metaText, load, pause, resume, resetAccount } = useColors(props.api)
const failed = ref(new Set<string>())
const failedKey = (gid: number | string) => String(gid)
function failedIcon(gid: number | string) { failed.value.add(failedKey(gid)) }
defineExpose({ load, pause, resume, resetAccount, error })
// 外壳挂载后把 active 由 false 翻到 true，首次加载靠这条 watch 触发。
watch(() => props.active, value => { if (value) void resume(); else pause() }, { flush: 'sync' })
onMounted(() => { if (props.active) void resume(); else pause() })
</script>
<template>
  <div class="stack colors-page" data-vue-page :aria-busy="loading">
    <section class="panel">
      <div class="panel-head">
        <h2>色卡矩阵</h2>
        <span id="cl-meta" class="muted">{{ metaText }}</span>
      </div>
      <div class="table-wrap">
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
                <td v-for="(cell, index) in row.cells" :key="index" class="mm-cell" :class="{ empty: cell.state === 'empty' }">
                  <template v-if="cell.state === 'empty'">—</template>
                  <template v-else-if="cell.state === 'card'">
                    <b class="cc-label" :title="cell.cell.names">{{ cell.cell.label }}</b>
                    <small class="cc-names">{{ cell.cell.names }}</small>
                    <span class="pet-color-card" role="img" :aria-label="cell.cell.names" :title="cell.cell.names"><ColorCardFace :card-id="cell.cell.card_id" :base-color="cell.cell.base_color" :mix-color="cell.cell.mix_color" /></span>
                  </template>
                  <template v-else>
                    <span v-for="pet in cell.pets" :key="pet.gid" class="mm-pet" :data-mm="pet.gid">
                      <img v-if="pet.icon_url && !failed.has(failedKey(pet.gid))" :src="pet.icon_url" alt="" loading="lazy" @error="failedIcon(pet.gid)">
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
    <div class="overview-lower">
      <section class="panel">
        <div class="panel-head"><h2>赛季卡</h2><span id="cl-seasonal-count" class="muted">{{ data ? data.seasonal.length + ' 只' : '' }}</span></div>
        <div id="cl-seasonal" class="bl-chips">
          <span v-for="pet in data?.seasonal || []" :key="pet.gid" class="mm-pet" :data-mm="pet.gid">
            <img v-if="pet.icon_url && !failed.has(failedKey(pet.gid))" :src="pet.icon_url" alt="" loading="lazy" @error="failedIcon(pet.gid)">
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
            <img v-if="pet.icon_url && !failed.has(failedKey(pet.gid))" :src="pet.icon_url" alt="" loading="lazy" @error="failedIcon(pet.gid)">
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
.colors-page { max-width: none; }
#cl-matrix .cc-label { font-size: var(--fs-xs); }
#cl-matrix .cc-names { display: block; font-size: var(--fs-2xs); color: var(--muted); }
</style>
