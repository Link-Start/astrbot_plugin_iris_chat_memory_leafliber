<template>
  <div class="l3-graph-view">
    <ComponentDisabled
      :status="status"
      :error="error"
      :error-type="errorType"
      component-name="L3 图谱"
      @retry="refreshState"
    >
      <v-row>
        <v-col cols="12">
          <v-card color="surface" variant="flat">
            <v-tabs v-model="activeTab" color="primary" grow>
              <v-tab value="graph">
                <v-icon icon="mdi-graph" class="mr-2" />
                图谱可视化
              </v-tab>
              <v-tab value="nodes">
                <v-icon icon="mdi-circle-multiple" class="mr-2" />
                节点列表
              </v-tab>
              <v-tab value="edges">
                <v-icon icon="mdi-arrow-right-bold" class="mr-2" />
                关系列表
              </v-tab>
            </v-tabs>
          </v-card>
        </v-col>
      </v-row>

      <v-window v-model="activeTab" class="mt-4">
        <v-window-item value="graph">
          <v-row>
            <v-col cols="12" lg="8">
              <L3GraphCanvas
                ref="canvasRef"
                :nodes="memoryStore.l3Graph.nodes"
                :edges="memoryStore.l3Graph.edges"
                :loading="memoryStore.l3Loading"
                @reload="loadGraph"
                @expand-node="handleExpandNode"
              />
            </v-col>
            <v-col cols="12" lg="4">
              <L3ControlPanel
                :nodes="memoryStore.l3Graph.nodes"
                :edges="memoryStore.l3Graph.edges"
                :loading="memoryStore.l3Loading"
                :depth="memoryStore.l3Depth"
                :max-nodes="memoryStore.l3MaxNodes"
                :start-node="memoryStore.l3StartNode"
                :search-results="memoryStore.l3SearchResults"
                :search-loading="memoryStore.l3SearchLoading"
                :search-keyword="memoryStore.l3SearchKeyword"
                @search="handleSearch"
                @clear-search="handleClearSearch"
                @update:depth="handleDepthChange"
                @update:max-nodes="handleMaxNodesChange"
                @reload="loadGraph"
                @clear-start="handleClearStart"
                @focus-node="handleFocusNode"
              />
            </v-col>
          </v-row>

          <v-row class="mt-4">
            <v-col cols="12">
              <v-card color="surface" variant="flat">
                <v-card-title>
                  <v-icon icon="mdi-information" class="mr-2" />
                  L3 知识图谱说明
                </v-card-title>
                <v-card-text>
                  <v-alert type="info" variant="tonal" density="compact">
                    <div class="text-body-2">
                      <strong>L3 知识图谱（Semantic Memory）</strong> 是结构化的长期记忆，存储实体关系和核心特征。
                      支持多跳推理和图谱可视化。拖拽节点可调整位置，滚轮缩放，悬停节点高亮其一度邻居，
                      点击节点或边查看详情并以此展开图谱。使用搜索快速定位节点，结果点击会在图上聚焦高亮。
                    </div>
                  </v-alert>
                </v-card-text>
              </v-card>
            </v-col>
          </v-row>
        </v-window-item>

        <v-window-item value="nodes">
          <v-row>
            <v-col cols="12">
              <L3NodeListPanel
                :nodes="memoryStore.l3Nodes"
                :loading="memoryStore.l3NodesLoading"
                :deleting="deletingL3Nodes"
                :initial-keyword="memoryStore.l3NodesKeyword"
                @search="handleNodesSearch"
                @delete="handleDeleteNodes"
                @focus-node="handleFocusNode"
              />
            </v-col>
          </v-row>
        </v-window-item>

        <v-window-item value="edges">
          <v-row>
            <v-col cols="12">
              <L3EdgeListPanel
                :edges="memoryStore.l3Edges"
                :loading="memoryStore.l3EdgesLoading"
                :initial-keyword="memoryStore.l3EdgesKeyword"
                @search="handleEdgesSearch"
                @delete="handleDeleteEdge"
                @focus-node="handleFocusNode"
              />
            </v-col>
          </v-row>
        </v-window-item>
      </v-window>
    </ComponentDisabled>

    <v-dialog v-model="deleteDialog" max-width="400">
      <v-card>
        <v-card-title class="d-flex align-center">
          <v-icon icon="mdi-alert-circle" color="warning" class="mr-2" />
          确认删除
        </v-card-title>
        <v-card-text>{{ deleteMessage }}</v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="deleteDialog = false">取消</v-btn>
          <v-btn color="error" variant="tonal" :loading="deleting" @click="confirmDelete">
            确认删除
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useMemoryStore } from '@/stores'
import { useComponentState } from '@/composables/useComponentState'
import ComponentDisabled from '@/components/ComponentDisabled.vue'
import L3GraphCanvas from '@/components/l3/L3GraphCanvas.vue'
import L3ControlPanel from '@/components/l3/L3ControlPanel.vue'
import L3NodeListPanel from '@/components/l3/L3NodeListPanel.vue'
import L3EdgeListPanel from '@/components/l3/L3EdgeListPanel.vue'

const memoryStore = useMemoryStore()
const { status, error, errorType, refreshState } = useComponentState('l3_kg')

const activeTab = ref('graph')
const canvasRef = ref<InstanceType<typeof L3GraphCanvas> | null>(null)

// 删除确认弹窗（节点/边共用）
const deleteDialog = ref(false)
const deleting = ref(false)
const deleteMessage = ref('')
const deleteAction = ref<() => Promise<void>>(async () => {})
const deletingL3Nodes = ref(false)

const loadGraph = () => memoryStore.fetchL3Graph()

const handleExpandNode = (nodeId: string) => {
  memoryStore.expandFromNode(nodeId)
}

// ---- 搜索 ----
const handleSearch = (keyword: string) => memoryStore.searchL3(keyword)
const handleClearSearch = () => memoryStore.clearL3Search()

// ---- 深度 / 节点数变更后立即重载 ----
const handleDepthChange = (depth: number) => {
  memoryStore.setDepth(depth)
  loadGraph()
}
const handleMaxNodesChange = (maxNodes: number) => {
  memoryStore.setMaxNodes(maxNodes)
  loadGraph()
}

const handleClearStart = () => {
  memoryStore.l3StartNode = null
  loadGraph()
}

// ---- 聚焦节点（来自搜索结果 / 列表点击）：切到图谱 Tab 并在画布上聚焦 ----
const handleFocusNode = async (nodeId: string) => {
  if (activeTab.value !== 'graph') {
    activeTab.value = 'graph'
    await nextTick()
  }
  // 等待画布就绪后调用其暴露的 focusNode
  await nextTick()
  canvasRef.value?.focusNode(nodeId)
}

// ---- 节点列表 ----
const handleNodesSearch = (keyword?: string) => memoryStore.fetchL3Nodes(keyword)
const handleDeleteNodes = (ids: string[]) => {
  deleteMessage.value =
    ids.length === 1
      ? '确定要删除该节点吗？与之关联的关系也将被删除。此操作不可撤销。'
      : `确定要删除 ${ids.length} 个节点吗？与之关联的关系也将被删除。此操作不可撤销。`
  deleteAction.value = async () => {
    deletingL3Nodes.value = true
    try {
      await memoryStore.deleteL3Nodes(ids)
    } finally {
      deletingL3Nodes.value = false
    }
  }
  deleteDialog.value = true
}

// ---- 关系列表 ----
const handleEdgesSearch = (keyword?: string) => memoryStore.fetchL3Edges(keyword)
const handleDeleteEdge = (sourceId: string, targetId: string, relation: string) => {
  deleteMessage.value = `确定要删除该关系吗？此操作不可撤销。`
  deleteAction.value = async () => {
    await memoryStore.deleteL3Edge(sourceId, targetId, relation)
  }
  deleteDialog.value = true
}

const confirmDelete = async () => {
  deleting.value = true
  try {
    await deleteAction.value()
    deleteDialog.value = false
  } catch (e) {
    console.error('删除失败:', e)
  } finally {
    deleting.value = false
  }
}

// ---- Tab 切换懒加载列表 ----
watch(activeTab, (tab) => {
  if (tab === 'nodes' && memoryStore.l3Nodes.length === 0) {
    memoryStore.fetchL3Nodes()
  } else if (tab === 'edges' && memoryStore.l3Edges.length === 0) {
    memoryStore.fetchL3Edges()
  }
})

const handleRefresh = () => {
  if (activeTab.value === 'graph') {
    loadGraph()
  } else if (activeTab.value === 'nodes') {
    memoryStore.fetchL3Nodes(memoryStore.l3NodesKeyword || undefined)
  } else if (activeTab.value === 'edges') {
    memoryStore.fetchL3Edges(memoryStore.l3EdgesKeyword || undefined)
  }
}

onMounted(() => {
  loadGraph()
  window.addEventListener('iris:refresh', handleRefresh)
})

onUnmounted(() => {
  window.removeEventListener('iris:refresh', handleRefresh)
})
</script>
