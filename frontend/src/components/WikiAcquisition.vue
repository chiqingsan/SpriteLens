<script setup lang="ts">
import type { WikiReference } from '../types/wikiReference'
defineProps<{ wiki: WikiReference; eggsOnly?: boolean }>()
</script>
<template>
  <template v-if="!eggsOnly">
    <h3>
      大世界分布
    </h3>
    <div v-if="wiki.areas.length" class="skill-list">
      <span v-for="area in wiki.areas" :key="area" class="skill-chip">
        {{ area }}
      </span>
    </div>
    <p v-else class="muted">
      来源尚未收录分布地点，不代表无法在大世界获得。
    </p>
    <h3>
      活动获取
    </h3>
    <article v-for="(activity, index) in wiki.activities" :key="index" class="wiki-source-card">
      <strong>
        {{ activity.name }}
      </strong>
      <p v-if="activity.window">
        活动时间：{{ activity.window }}
      </p>
      <p v-if="activity.note">
        {{ activity.note }}
      </p>
    </article>
    <p v-if="!wiki.activities.length" class="muted">
      暂无活动来源记录。
    </p>
    <p v-else class="wiki-footnote">
      历史活动保留供查询，不代表目前仍可参与。
    </p>
  </template>
  <h3>
    精灵蛋与特殊蛋来源
  </h3>
  <article v-for="(egg, index) in wiki.eggs" :key="index" class="wiki-source-card">
    <strong>
      {{ egg.name }}
    </strong>
    <p>
      {{ egg.description || '暂无描述' }}
    </p>
    <p v-for="source in egg.sources" :key="source" class="wiki-footnote">
      来源：{{ source }}
    </p>
  </article>
  <p v-if="!wiki.eggs.length" class="muted">
    来源尚未收录特殊蛋资料。
  </p>
</template>
