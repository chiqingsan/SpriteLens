<script setup lang="ts">
defineProps<{ ranges: { height: string; weight: string }; areas?: string[]; egg?: boolean }>()
</script>
<template>
  <section class="mini-panel mini-axes"><h4>{{ egg ? '精灵蛋' : '能力值' }} · 数据范围</h4>
    <div v-for="[key, label] in [['height', '身高'], ['weight', '体重']] as const" :key="key" class="mini-axis" :class="key">
      <b>{{ label }} {{ ranges[key] || '暂无数据' }}</b><div class="mini-axis-track"><i></i><i></i><i></i></div><div class="mini-thresholds"><span>最小参考值</span><span>最大参考值</span></div>
    </div>
    <div v-if="!egg" class="mini-habitat"><span>栖息分布</span><b>{{ areas?.join('、') || '暂无分布数据' }}</b></div>
  </section>
</template>
