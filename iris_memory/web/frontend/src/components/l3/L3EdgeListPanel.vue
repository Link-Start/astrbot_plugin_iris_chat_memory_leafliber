<template>
  <v-card color="surface" variant="flat">
    <v-card-title class="d-flex align-center">
      <v-icon icon="mdi-arrow-right-bold" color="secondary" class="mr-2" />
      关系列表
      <v-spacer />
      <v-text-field
        v-model="keyword"
        placeholder="搜索关系..."
        prepend-inner-icon="mdi-magnify"
        variant="outlined"
        density="compact"
        hide-details
        clearable
        style="max-width: 250px"
        @keyup.enter="handleSearch"
        @click:clear="handleClear"
      />
    </v-card-title>
    <v-card-text>
      <v-progress-linear v-if="loading" indeterminate color="primary" />
      <v-table v-else-if="edges.length > 0" density="compact" hover>
        <thead>
          <tr>
            <th>源节点</th>
            <th>关系</th>
            <th>目标节点</th>
            <th>置信度</th>
            <th>权重</th>
            <th>创建时间</th>
            <th class="text-center">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(edge, idx) in edges" :key="idx">
            <td>
              <v-chip
                size="small"
                :color="getTypeColor(edge.source.label)"
                variant="tonal"
                @click="emit('focus-node', edge.source.id)"
              >
                <v-icon :icon="getNodeIcon(edge.source.label)" start size="x-small" />
                {{ edge.source.name }}
              </v-chip>
            </td>
            <td>
              <v-chip size="small" variant="outlined">
                {{ getRelationLabel(edge.relation) }}
              </v-chip>
            </td>
            <td>
              <v-chip
                size="small"
                :color="getTypeColor(edge.target.label)"
                variant="tonal"
                @click="emit('focus-node', edge.target.id)"
              >
                <v-icon :icon="getNodeIcon(edge.target.label)" start size="x-small" />
                {{ edge.target.name }}
              </v-chip>
            </td>
            <td>
              <v-chip
                size="small"
                :color="getConfidenceColor(edge.confidence)"
                variant="tonal"
              >
                {{ (edge.confidence * 100).toFixed(0) }}%
              </v-chip>
            </td>
            <td>{{ edge.weight?.toFixed(2) ?? '-' }}</td>
            <td class="text-caption">{{ formatTime(edge.created_time) }}</td>
            <td class="text-center">
              <v-btn
                icon="mdi-delete"
                variant="text"
                size="small"
                color="error"
                @click="handleDelete(edge)"
              />
            </td>
          </tr>
        </tbody>
      </v-table>
      <div v-else class="text-center text-medium-emphasis py-12">
        <v-icon icon="mdi-arrow-right-bold-outline" size="80" class="mb-3" />
        <div class="text-h6">暂无关系数据</div>
        <div class="text-body-2 mt-2">L3 知识图谱中暂无关系</div>
      </div>
    </v-card-text>
  </v-card>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { L3EdgeDetail } from '@/types'
import {
  getNodeIcon,
  getTypeColor,
  getRelationLabel,
  getConfidenceColor,
  formatTime,
} from '@/composables/l3Constants'

const props = defineProps<{
  edges: L3EdgeDetail[]
  loading: boolean
  initialKeyword?: string
}>()

const emit = defineEmits<{
  search: [keyword: string | undefined]
  delete: [sourceId: string, targetId: string, relation: string]
  'focus-node': [nodeId: string]
}>()

const keyword = ref(props.initialKeyword || '')

const handleSearch = () => emit('search', keyword.value || undefined)
const handleClear = () => {
  keyword.value = ''
  emit('search', undefined)
}
const handleDelete = (edge: L3EdgeDetail) =>
  emit('delete', edge.source.id, edge.target.id, edge.relation)
</script>
