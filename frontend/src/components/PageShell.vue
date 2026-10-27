<script setup lang="ts">
/* 页面骨架：工具栏 + 主体两段。各页面的顶部行不再各自拼 header，
   统一成「左侧上下文 / 右侧操作 / 下方主体」的同一节奏。 */
defineProps<{ busy?: boolean }>()
</script>

<template>
  <div class="ui-page" :aria-busy="busy || undefined">
    <header v-if="$slots.toolbar" class="ui-page-toolbar"><slot name="toolbar" /></header>
    <slot />
  </div>
</template>
