<template>
  <v-card color="surface" variant="flat" class="mb-4">
    <v-card-title>
      <v-icon icon="mdi-magnify" class="mr-2" />
      搜索图谱
    </v-card-title>
    <v-card-text>
      <v-text-field
        v-model="keyword"
        placeholder="搜索节点或关系..."
        prepend-inner-icon="mdi-magnify"
        variant="outlined"
        density="compact"
        hide-details
        clearable
        @keyup.enter="handleSearch"
        @click:clear="handleClear"
      />
      <v-btn
        color="primary"
        size="small"
        class="mt-2"
        block
        :loading="searchLoading"
        @click="handleSearch"
      >
        搜索
      </v-btn>
    </v-card-text>
  </v-card>

  <v-card
    v-if="searchResults.nodes.length > 0 || searchResults.edges.length > 0"
    color="surface"
    variant="flat"
    class="mb-4"
  >
    <v-card-title class="d-flex align-center">
      <v-icon icon="mdi-magnify" class="mr-2" />
      搜索结果
      <v-spacer />
      <v-btn icon="mdi-close" variant="text" size="small" @click="handleClear" />
    </v-card-title>
    <v-card-text>
      <div v-if="searchResults.nodes.length > 0" class="mb-3">
        <div class="text-caption text-medium-emphasis mb-2">
          节点 ({{ searchResults.nodes.length }})
        </div>
        <v-list density="compact" class="pa-0 bg-transparent">
          <v-list-item
            v-for="node in searchResults.nodes"
            :key="node.id"
            :prepend-icon="getNodeIcon(node.label)"
            @click="emit('focus-node', node.id)"
          >
            <v-list-item-title>{{ node.name || node.id }}</v-list-item-title>
            <v-list-item-subtitle>{{ getNodeLabel(node.label) }}</v-list-item-subtitle>
            <template #append>
              <v-chip size="x-small" :color="getTypeColor(node.label)" variant="tonal">
                {{ (node.confidence * 100).toFixed(0) }}%
              </v-chip>
            </template>
          </v-list-item>
        </v-list>
      </div>
      <div v-if="searchResults.edges.length > 0">
        <div class="text-caption text-medium-emphasis mb-2">
          关系 ({{ searchResults.edges.length }})
        </div>
        <v-list density="compact" class="pa-0 bg-transparent">
          <v-list-item
            v-for="(edge, idx) in searchResults.edges"
            :key="idx"
            prepend-icon="mdi-arrow-right-bold"
            @click="emit('focus-node', edge.source.id)"
          >
            <v-list-item-title>{{ getRelationLabel(edge.relation) }}</v-list-item-title>
            <v-list-item-subtitle>
              {{ edge.source.name }} → {{ edge.target.name }}
            </v-list-item-subtitle>
          </v-list-item>
        </v-list>
      </div>
    </v-card-text>
  </v-card>

  <v-card color="surface" variant="flat" class="mb-4">
    <v-card-title>
      <v-icon icon="mdi-tune" class="mr-2" />
      图谱控制
    </v-card-title>
    <v-card-text>
      <div class="mb-4">
        <div class="text-caption text-medium-emphasis mb-1">拓展深度</div>
        <v-slider
          :model-value="depth"
          :min="1"
          :max="3"
          :step="1"
          thumb-label
          @update:model-value="(v: number) => emit('update:depth', v)"
        />
      </div>

      <div class="mb-4">
        <div class="text-caption text-medium-emphasis mb-1">最大节点数</div>
        <v-slider
          :model-value="maxNodes"
          :min="10"
          :max="50"
          :step="5"
          thumb-label
          @update:model-value="(v: number) => emit('update:maxNodes', v)"
        />
      </div>

      <div class="mb-4">
        <div class="text-caption text-medium-emphasis mb-1">起始节点</div>
        <v-chip
          v-if="startNode"
          color="accent"
          variant="tonal"
          size="small"
          closable
          @click:close="emit('clear-start')"
        >
          <v-icon :icon="getNodeIcon(startNode.label)" start size="small" />
          {{ startNode.name || startNode.id }}
        </v-chip>
        <span v-else class="text-medium-emphasis text-body-2">随机选择</span>
      </div>

      <v-btn color="primary" block :loading="loading" @click="emit('reload')">
        <v-icon icon="mdi-refresh" class="mr-1" />
        重新加载
      </v-btn>
    </v-card-text>
  </v-card>

  <v-card color="surface" variant="flat" class="mb-4">
    <v-card-title>
      <v-icon icon="mdi-chart-pie" class="mr-2" />
      图谱统计
    </v-card-title>
    <v-card-text>
      <v-row>
        <v-col cols="6" class="text-center">
          <div class="text-h4 font-weight-bold text-primary">{{ nodes.length }}</div>
          <div class="text-caption text-medium-emphasis">节点</div>
        </v-col>
        <v-col cols="6" class="text-center">
          <div class="text-h4 font-weight-bold text-secondary">{{ edges.length }}</div>
          <div class="text-caption text-medium-emphasis">关系</div>
        </v-col>
      </v-row>

      <v-divider class="my-3" />

      <div class="text-caption text-medium-emphasis mb-2">节点类型</div>
      <v-chip-group column>
        <v-chip
          v-for="(count, type) in nodeTypeStats"
          :key="type"
          size="small"
          variant="tonal"
          :color="getTypeColor(type)"
        >
          <v-icon :icon="getNodeIcon(type)" start size="small" />
          {{ getNodeLabel(type) }}: {{ count }}
        </v-chip>
      </v-chip-group>

      <div class="text-caption text-medium-emphasis mb-2 mt-3">关系类型</div>
      <v-chip-group column>
        <v-chip
          v-for="(count, type) in relationTypeStats"
          :key="type"
          size="small"
          variant="outlined"
        >
          {{ getRelationLabel(type) }}: {{ count }}
        </v-chip>
      </v-chip-group>
    </v-card-text>
  </v-card>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import type { KGNode, KGEdge, L3SearchNodeResult, L3SearchEdgeResult } from '@/types'
import {
  getNodeIcon,
  getTypeColor,
  getNodeLabel,
  getRelationLabel,
} from '@/composables/l3Constants'

const props = defineProps<{
  nodes: KGNode[]
  edges: KGEdge[]
  loading: boolean
  depth: number
  maxNodes: number
  startNode: KGNode | null
  searchResults: { nodes: L3SearchNodeResult[]; edges: L3SearchEdgeResult[] }
  searchLoading: boolean
  searchKeyword: string
}>()

const emit = defineEmits<{
  search: [keyword: string]
  'clear-search': []
  'update:depth': [depth: number]
  'update:maxNodes': [maxNodes: number]
  reload: []
  'clear-start': []
  'focus-node': [nodeId: string]
}>()

const keyword = ref(props.searchKeyword)

watch(
  () => props.searchKeyword,
  (v) => {
    if (v !== keyword.value) keyword.value = v
  }
)

const handleSearch = () => {
  const v = keyword.value?.trim()
  if (v) emit('search', v)
}

const handleClear = () => {
  keyword.value = ''
  emit('clear-search')
}

const nodeTypeStats = computed(() => {
  const stats: Record<string, number> = {}
  props.nodes.forEach((n) => {
    stats[n.label] = (stats[n.label] || 0) + 1
  })
  return stats
})

const relationTypeStats = computed(() => {
  const stats: Record<string, number> = {}
  props.edges.forEach((e) => {
    stats[e.relation] = (stats[e.relation] || 0) + 1
  })
  return stats
})
</script>
