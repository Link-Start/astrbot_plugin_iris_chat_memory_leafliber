<template>
  <v-card color="surface" variant="flat">
    <v-card-title class="d-flex align-center">
      <v-icon icon="mdi-circle-multiple" color="primary" class="mr-2" />
      节点列表
      <v-spacer />
      <v-text-field
        v-model="keyword"
        placeholder="搜索节点..."
        prepend-inner-icon="mdi-magnify"
        variant="outlined"
        density="compact"
        hide-details
        clearable
        style="max-width: 250px"
        @keyup.enter="handleSearch"
        @click:clear="handleClear"
      />
      <v-btn
        v-if="selectedIds.length > 0"
        color="error"
        variant="tonal"
        size="small"
        class="ml-2"
        :loading="deleting"
        @click="handleDeleteSelected"
      >
        <v-icon icon="mdi-delete" class="mr-1" />
        删除选中 ({{ selectedIds.length }})
      </v-btn>
    </v-card-title>
    <v-card-text>
      <v-progress-linear v-if="loading" indeterminate color="primary" />
      <v-table v-else-if="nodes.length > 0" density="compact" hover>
        <thead>
          <tr>
            <th class="text-center" style="width: 40px">
              <v-checkbox
                :model-value="selectAll"
                density="compact"
                hide-details
                @update:model-value="toggleSelectAll"
              />
            </th>
            <th>ID</th>
            <th>名称</th>
            <th>类型</th>
            <th>置信度</th>
            <th>访问次数</th>
            <th>创建时间</th>
            <th class="text-center">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="node in nodes" :key="node.id">
            <td class="text-center">
              <v-checkbox
                :model-value="selectedIds.includes(node.id)"
                density="compact"
                hide-details
                @update:model-value="toggleSelect(node.id)"
              />
            </td>
            <td class="text-caption">{{ node.id }}</td>
            <td>
              <a class="node-link" @click="emit('focus-node', node.id)">{{ node.name }}</a>
            </td>
            <td>
              <v-chip size="small" :color="getTypeColor(node.label)" variant="tonal">
                <v-icon :icon="getNodeIcon(node.label)" start size="x-small" />
                {{ getNodeLabel(node.label) }}
              </v-chip>
            </td>
            <td>
              <v-chip
                size="small"
                :color="getConfidenceColor(node.confidence)"
                variant="tonal"
              >
                {{ (node.confidence * 100).toFixed(0) }}%
              </v-chip>
            </td>
            <td>{{ node.access_count ?? '-' }}</td>
            <td class="text-caption">{{ formatTime(node.created_time) }}</td>
            <td class="text-center">
              <v-btn
                icon="mdi-delete"
                variant="text"
                size="small"
                color="error"
                @click="handleDeleteSingle(node.id)"
              />
            </td>
          </tr>
        </tbody>
      </v-table>
      <div v-else class="text-center text-medium-emphasis py-12">
        <v-icon icon="mdi-circle-multiple-outline" size="80" class="mb-3" />
        <div class="text-h6">暂无节点数据</div>
        <div class="text-body-2 mt-2">L3 知识图谱中暂无节点</div>
      </div>
    </v-card-text>
  </v-card>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import type { L3NodeDetail } from '@/types'
import {
  getNodeIcon,
  getTypeColor,
  getNodeLabel,
  getConfidenceColor,
  formatTime,
} from '@/composables/l3Constants'

const props = defineProps<{
  nodes: L3NodeDetail[]
  loading: boolean
  deleting: boolean
  initialKeyword?: string
}>()

const emit = defineEmits<{
  search: [keyword: string | undefined]
  delete: [ids: string[]]
  'focus-node': [nodeId: string]
}>()

const keyword = ref(props.initialKeyword || '')
const selectedIds = ref<string[]>([])

const selectAll = computed(
  () => props.nodes.length > 0 && selectedIds.value.length === props.nodes.length
)

const toggleSelect = (id: string) => {
  const idx = selectedIds.value.indexOf(id)
  if (idx >= 0) selectedIds.value.splice(idx, 1)
  else selectedIds.value.push(id)
}

const toggleSelectAll = (checked: boolean | null) => {
  selectedIds.value = checked ? props.nodes.map((n) => n.id) : []
}

const handleSearch = () => emit('search', keyword.value || undefined)
const handleClear = () => {
  keyword.value = ''
  emit('search', undefined)
}

const handleDeleteSingle = (id: string) => emit('delete', [id])
const handleDeleteSelected = () => {
  emit('delete', [...selectedIds.value])
  selectedIds.value = []
}
</script>

<style scoped>
.node-link {
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 2px;
}
.node-link:hover {
  opacity: 0.8;
}
</style>
