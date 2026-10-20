<script setup lang="ts">
defineProps<{ male: number; female: number }>()
</script>
<template>
  <section class="mini-gender"><h4>公母比例</h4>
    <div v-if="male || female" class="mini-gender-content">
      <i :style="{ background: `conic-gradient(var(--male-strong) 0 ${male}%, var(--female-strong) ${male}% 100%)` }"><em></em></i>
      <div><span><small class="female"></small>雌性 <b>{{ female }}%</b></span><span><small class="male"></small>雄性 <b>{{ male }}%</b></span></div>
    </div><p v-else>暂无比例数据</p>
  </section>
</template>
