<script setup lang="ts">
defineProps<{ name: string }>()
</script>
<template>
  <svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use :href="`/static/icons/sprite.svg#${name}`"></use></svg>
</template>
