<script setup lang="ts">
import { computed, ref } from 'vue'
import type { EggParent, EggPickupOrigin, EggVoicePrediction } from '../types/eggBox'
import UiIcon from './UiIcon.vue'

const props = defineProps<{ pickup: EggPickupOrigin; prediction?: EggVoicePrediction | null }>()

const mother = computed(() => props.pickup.mother)
const fathers = computed(() => props.pickup.fathers)
// 声音遗传：母本与候选父本取平均向下取整；候选父本结果不一致时只给区间。
const predictionText = computed(() => {
  const prediction = props.prediction
  if (!prediction) return ''
  const tags = prediction.tags.join(' / ')
  if (prediction.voice_db !== null) {
    return `${prediction.voice_db} dB · ${tags || '未达参考奖牌标准'}`
  }
  return `${prediction.range[0]} ~ ${prediction.range[1]} dB · ${tags || '候选父本不同，暂不自动打标'}`
})
// 头像 404 时回退首字占位，避免碎图图标；按实例 ID 记录失败，切蛋后可重试。
const failedAvatars = ref<ReadonlySet<number>>(new Set())

function showAvatar(parent: EggParent) {
  return !!parent.icon_url && !failedAvatars.value.has(parent.instance_id)
}
function avatarFailed(parent: EggParent) {
  const next = new Set(failedAvatars.value)
  next.add(parent.instance_id)
  failedAvatars.value = next
}
function initial(parent: EggParent) {
  return Array.from(parent.name.trim())[0] || '?'
}
function parentLabel(parent: EggParent) {
  return `${parent.name || '未知精灵'} #${parent.instance_id}`
}
</script>

<template>
  <section class="eggbox-parents" aria-labelledby="eggbox-parents-heading">
    <div class="eggbox-section-heading">
      <h3 id="eggbox-parents-heading">亲代关联</h3>
      <span>{{ pickup.nest_kind === 'academy' ? '学院绿窝' : '普通窝' }} · 收取时记录</span>
    </div>
    <div class="eggbox-parent-groups">
      <div class="eggbox-parent-group">
        <h4><UiIcon name="gender-female" :aria-hidden="true" />关联母本</h4>
        <div v-if="mother" class="eggbox-parent-cards">
        <button type="button" class="eggbox-parent-card eggbox-parent-card--mother"
          :data-reveal-pet="mother.instance_id" :title="`查看${parentLabel(mother)}`"
          :aria-label="`查看关联母本 ${parentLabel(mother)}`">
          <span class="eggbox-parent-avatar" aria-hidden="true">
            <img v-if="showAvatar(mother)" :src="mother.icon_url" alt="" loading="lazy" @error="avatarFailed(mother)" />
            <span v-else class="eggbox-parent-avatar-fallback">{{ initial(mother) }}</span>
          </span>
          <span class="eggbox-parent-copy">
            <b>{{ mother.name || '未知精灵' }}</b>
            <small>#{{ mother.instance_id }}</small>
          </span>
          <UiIcon name="chevron-right" :aria-hidden="true" />
        </button>
        </div>
        <p v-else class="eggbox-parent-empty">收取时窝内母本不唯一，未能确认。</p>
      </div>
      <div class="eggbox-parent-group">
        <h4><UiIcon name="gender-male" :aria-hidden="true" />候选父本</h4>
        <div v-if="fathers.length" class="eggbox-parent-cards">
          <button v-for="father in fathers" :key="father.instance_id" type="button"
            class="eggbox-parent-card eggbox-parent-card--father" :data-reveal-pet="father.instance_id"
            :title="`查看${parentLabel(father)}`" :aria-label="`查看候选父本 ${parentLabel(father)}`">
            <span class="eggbox-parent-avatar" aria-hidden="true">
              <img v-if="showAvatar(father)" :src="father.icon_url" alt="" loading="lazy" @error="avatarFailed(father)" />
              <span v-else class="eggbox-parent-avatar-fallback">{{ initial(father) }}</span>
            </span>
            <span class="eggbox-parent-copy">
              <b>{{ father.name || '未知精灵' }}</b>
              <small>#{{ father.instance_id }}</small>
            </span>
            <UiIcon name="chevron-right" :aria-hidden="true" />
          </button>
        </div>
        <p v-else class="eggbox-parent-empty">收取时没有可用的配对名单。</p>
      </div>
    </div>
    <p v-if="prediction" class="eggbox-parent-prediction">
      <UiIcon name="activity" :aria-hidden="true" />
      <span>预测声音 <b>{{ predictionText }}</b>（母本与父本取平均、向下取整）</span>
    </p>
    <small class="filter-note">
      候选父本来自收取前的配对名单，不代表实际父本。<template v-if="pickup.pairing_stale">配对快照有待同步，仅供参考。</template>
    </small>
  </section>
</template>
