<template>
  <div class="dashboard">
    <v-row dense>
      <v-col cols="12">
        <v-card color="surface" variant="flat" class="system-bar">
          <v-card-text class="d-flex align-center flex-wrap ga-3 pa-3">
            <v-chip
              :color="globalStatusColor"
              variant="tonal"
              size="small"
              prepend-icon="mdi-circle-medium"
            >
              {{ globalStatusText }}
            </v-chip>
            <span class="text-caption text-medium-emphasis">
              <v-icon icon="mdi-tag-outline" size="x-small" class="mr-1" />
              v{{ systemStats?.version || '—' }}
            </span>
            <span class="text-caption text-medium-emphasis">
              <v-icon icon="mdi-clock-outline" size="x-small" class="mr-1" />
              {{ uptime }}
            </span>
            <v-spacer />
            <div class="d-flex flex-wrap ga-1">
              <v-chip
                v-for="(state, key) in componentStates"
                :key="key"
                size="x-small"
                :color="getStatusColor(state.status)"
                variant="tonal"
              >
                <v-icon
                  :icon="getStatusIcon(state.status)"
                  size="x-small"
                  :class="{ 'animate-spin': state.status === 'initializing' }"
                  class="mr-1"
                />
                {{ getComponentName(String(key)) }}
                <v-tooltip v-if="state.error" activator="parent" location="bottom">
                  <div class="text-caption">
                    <div class="font-weight-bold mb-1">{{ getErrorTypeName(state.error_type) }}</div>
                    <div>{{ state.error }}</div>
                  </div>
                </v-tooltip>
              </v-chip>
            </div>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <v-row dense class="mt-1">
      <v-col cols="12" md="4">
        <v-card
          color="surface"
          variant="flat"
          class="memory-card"
          :class="{ 'component-disabled': !isL1Available }"
        >
          <v-card-item>
            <template #prepend>
              <v-avatar color="primary" variant="tonal" size="36">
                <v-icon icon="mdi-lightning-bolt" size="20" />
              </v-avatar>
            </template>
            <v-card-title class="text-body-1">L1 缓冲</v-card-title>
            <v-card-subtitle class="text-caption">短期记忆 · 消息缓冲</v-card-subtitle>
          </v-card-item>
          <v-card-text v-if="isL1Available" class="memory-content">
            <div class="d-flex align-baseline ga-2">
              <span class="text-h4 font-weight-bold">{{ l1QueueLength }}</span>
              <span class="text-caption text-medium-emphasis">
                / {{ l1MaxCapacity ?? '∞' }} 条消息
              </span>
            </div>
            <div class="text-caption text-medium-emphasis mt-1">分群设计 · 队列总长</div>
          </v-card-text>
          <v-card-text v-else class="text-center py-3 memory-content">
            <v-icon icon="mdi-block-helper" color="error" size="large" />
            <div class="status-text-unavailable mt-1">
              {{ getComponentDisabledReason('l1_buffer') }}
            </div>
          </v-card-text>
        </v-card>
      </v-col>

      <v-col cols="12" md="4">
        <v-card
          color="surface"
          variant="flat"
          class="memory-card"
          :class="{ 'component-disabled': !isL2Available }"
        >
          <v-card-item>
            <template #prepend>
              <v-avatar color="secondary" variant="tonal" size="36">
                <v-icon icon="mdi-database" size="20" />
              </v-avatar>
            </template>
            <v-card-title class="text-body-1">L2 记忆</v-card-title>
            <v-card-subtitle class="text-caption">长期记忆 · 向量检索</v-card-subtitle>
          </v-card-item>
          <v-card-text v-if="isL2Available" class="memory-content">
            <div class="d-flex align-baseline ga-2">
              <span class="text-h4 font-weight-bold">{{ formatNumber(l2TotalCount) }}</span>
              <span class="text-caption text-medium-emphasis">条记忆</span>
            </div>
            <div class="text-caption text-medium-emphasis mt-1">
              涉及 {{ l2GroupCount }} 个群聊
            </div>
          </v-card-text>
          <v-card-text v-else class="text-center py-3 memory-content">
            <v-icon icon="mdi-block-helper" color="error" size="large" />
            <div class="status-text-unavailable mt-1">
              {{ getComponentDisabledReason('l2_memory') }}
            </div>
          </v-card-text>
        </v-card>
      </v-col>

      <v-col cols="12" md="4">
        <v-card
          color="surface"
          variant="flat"
          class="memory-card"
          :class="{ 'component-disabled': !isL3Available }"
        >
          <v-card-item>
            <template #prepend>
              <v-avatar color="accent" variant="tonal" size="36">
                <v-icon icon="mdi-graph" size="20" />
              </v-avatar>
            </template>
            <v-card-title class="text-body-1">L3 知识图谱</v-card-title>
            <v-card-subtitle class="text-caption">结构化知识 · 关系网络</v-card-subtitle>
          </v-card-item>
          <v-card-text v-if="isL3Available" class="memory-content">
            <div class="d-flex ga-4">
              <div class="text-center">
                <span class="text-h4 font-weight-bold">{{ formatNumber(kgNodeCount) }}</span>
                <div class="text-caption">节点</div>
              </div>
              <div class="text-center">
                <span class="text-h4 font-weight-bold">{{ formatNumber(kgEdgeCount) }}</span>
                <div class="text-caption">边</div>
              </div>
            </div>
          </v-card-text>
          <v-card-text v-else class="text-center py-3 memory-content">
            <v-icon icon="mdi-block-helper" color="error" size="large" />
            <div class="status-text-unavailable mt-1">
              {{ getComponentDisabledReason('l3_kg') }}
            </div>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <v-row dense class="mt-1">
      <v-col cols="12">
        <v-card color="surface" variant="flat">
          <v-card-item>
            <template #prepend>
              <v-icon icon="mdi-counter" color="info" />
            </template>
            <v-card-title class="text-body-1">Token 消耗</v-card-title>
          </v-card-item>
          <v-card-text class="pt-0">
            <v-table density="compact" class="bg-transparent token-table">
              <thead>
                <tr>
                  <th>模块</th>
                  <th class="text-right">输入 Token</th>
                  <th class="text-right">输出 Token</th>
                  <th class="text-right">调用次数</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(stat, module) in tokenStats" :key="module">
                  <td class="font-weight-medium">{{ getModuleName(module) }}</td>
                  <td class="text-right text-primary">{{ formatNumber(stat.total_input_tokens) }}</td>
                  <td class="text-right text-secondary">{{ formatNumber(stat.total_output_tokens) }}</td>
                  <td class="text-right">{{ stat.total_calls }}</td>
                </tr>
              </tbody>
            </v-table>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <v-row dense class="mt-1" v-if="hasKgTypeData">
      <v-col cols="12" sm="6">
        <v-card color="surface" variant="flat" class="h-100">
          <v-card-title class="text-subtitle-2 d-flex align-center">
            <v-icon icon="mdi-circle-multiple" size="small" class="mr-1" />
            节点类型分布
          </v-card-title>
          <v-card-text>
            <div
              v-for="(count, type) in kgStats?.node_types"
              :key="'node-' + type"
              class="d-flex align-center mb-2"
            >
              <span class="text-body-2 type-label">{{ type }}</span>
              <v-progress-linear
                :model-value="(count / kgNodeCount) * 100"
                color="primary"
                height="18"
                rounded
                class="flex-grow-1"
              />
              <span class="ml-2 text-caption" style="min-width: 32px; text-align: right;">{{ count }}</span>
            </div>
          </v-card-text>
        </v-card>
      </v-col>

      <v-col cols="12" sm="6">
        <v-card color="surface" variant="flat" class="h-100">
          <v-card-title class="text-subtitle-2 d-flex align-center">
            <v-icon icon="mdi-arrow-decision" size="small" class="mr-1" />
            关系类型分布
          </v-card-title>
          <v-card-text>
            <div
              v-for="(count, type) in kgStats?.relation_types"
              :key="'rel-' + type"
              class="d-flex align-center mb-2"
            >
              <span class="text-body-2 type-label">{{ type }}</span>
              <v-progress-linear
                :model-value="(count / kgEdgeCount) * 100"
                color="secondary"
                height="18"
                rounded
                class="flex-grow-1"
              />
              <span class="ml-2 text-caption" style="min-width: 32px; text-align: right;">{{ count }}</span>
            </div>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useStatsStore } from '@/stores'
import type { ComponentStatus, ErrorType, TokenStats } from '@/types'
import {
  COMPONENT_DISPLAY_NAMES,
  ERROR_TYPE_DISPLAY_NAMES,
  STATUS_DISPLAY_NAMES
} from '@/types'

const statsStore = useStatsStore()

const refreshInterval = ref<number | null>(null)

const componentStates = computed(() => statsStore.componentStates)
const systemStats = computed(() => statsStore.systemStats)
const tokenStats = computed((): Record<string, TokenStats> => statsStore.tokenStats || {})
const kgStats = computed(() => statsStore.kgStats)

const globalStatusColor = computed(() => {
  const status = statsStore.globalStatus
  if (status === 'available') return 'success'
  if (status === 'initializing') return 'warning'
  return 'grey'
})

const globalStatusText = computed(() => {
  const status = statsStore.globalStatus
  if (status === 'available') return '系统正常'
  if (status === 'initializing') return '正在初始化'
  return '等待启动'
})

const getComponentName = (key: string): string => {
  return COMPONENT_DISPLAY_NAMES[key] || key
}

const getStatusIcon = (status: ComponentStatus): string => {
  switch (status) {
    case 'available':
      return 'mdi-check-circle'
    case 'pending':
      return 'mdi-clock-outline'
    case 'initializing':
      return 'mdi-loading'
    case 'unavailable':
      return 'mdi-alert-circle'
    default:
      return 'mdi-help-circle'
  }
}

const getStatusColor = (status: ComponentStatus): string => {
  switch (status) {
    case 'available':
      return 'success'
    case 'pending':
    case 'initializing':
      return 'warning'
    case 'unavailable':
      return 'error'
    default:
      return 'grey'
  }
}

const getErrorTypeName = (errorType: ErrorType | null): string => {
  if (!errorType) return ''
  return ERROR_TYPE_DISPLAY_NAMES[errorType] || errorType
}

const isL1Available = computed(() => statsStore.isComponentAvailable('l1_buffer'))
const isL2Available = computed(() => statsStore.isComponentAvailable('l2_memory'))
const isL3Available = computed(() => statsStore.isComponentAvailable('l3_kg'))

const getComponentDisabledReason = (componentName: string): string => {
  const state = statsStore.getComponentState(componentName)
  if (state.status === 'pending' || state.status === 'initializing') {
    return '正在加载...'
  }
  if (state.error_type) {
    return ERROR_TYPE_DISPLAY_NAMES[state.error_type] || '不可用'
  }
  return '不可用'
}

const l1QueueLength = computed(() => statsStore.memoryStats?.l1?.total_messages ?? 0)
const l1MaxCapacity = computed(() => statsStore.memoryStats?.l1?.max_capacity)

const l2TotalCount = computed(() => statsStore.memoryStats?.l2?.total_count ?? 0)
const l2GroupCount = computed(() => statsStore.memoryStats?.l2?.group_count ?? 0)

const kgNodeCount = computed(() => kgStats.value?.node_count ?? 0)
const kgEdgeCount = computed(() => kgStats.value?.edge_count ?? 0)

const hasKgTypeData = computed(() => {
  const nt = kgStats.value?.node_types
  const rt = kgStats.value?.relation_types
  return (nt && Object.keys(nt).length > 0) || (rt && Object.keys(rt).length > 0)
})

const uptime = computed(() => {
  const seconds = systemStats.value?.uptime ?? 0
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  if (days > 0) return `${days} 天 ${hours} 小时`
  if (hours > 0) return `${hours} 小时 ${minutes} 分钟`
  return `${minutes} 分钟`
})

const getModuleName = (module: string): string => {
  const names: Record<string, string> = {
    global: '全局',
    l1_summarizer: 'L1 摘要器',
    llm_manager: 'LLM 管理器'
  }
  return names[module] || module
}

const formatNumber = (num: number): string => {
  if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M'
  if (num >= 1000) return (num / 1000).toFixed(1) + 'K'
  return num.toString()
}

const loadData = async () => {
  await statsStore.fetchAllStats()
}

const handleRefresh = () => {
  loadData()
}

onMounted(() => {
  loadData()
  refreshInterval.value = window.setInterval(loadData, 30000)
  window.addEventListener('iris:refresh', handleRefresh)
})

onUnmounted(() => {
  if (refreshInterval.value) {
    clearInterval(refreshInterval.value)
  }
  window.removeEventListener('iris:refresh', handleRefresh)
})
</script>

<style scoped>
.system-bar {
  border: 1px solid rgb(var(--v-theme-on-surface), 0.08);
}

.component-disabled {
  opacity: 0.6;
}

.memory-card {
  height: 100%;
  display: flex;
  flex-direction: column;
  border: 1px solid rgb(var(--v-theme-on-surface), 0.08);
}

.memory-card :deep(.v-card-item) {
  flex-shrink: 0;
}

.memory-card :deep(.v-card-text) {
  flex-grow: 1;
}

.memory-content {
  min-height: 72px;
}

.status-text-unavailable {
  font-size: 0.75rem;
  color: rgb(var(--v-theme-error));
  font-weight: 500;
}

.animate-spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

.token-table {
  border: 1px solid rgb(var(--v-theme-on-surface), 0.06);
  border-radius: 8px;
}

.type-label {
  min-width: 80px;
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
