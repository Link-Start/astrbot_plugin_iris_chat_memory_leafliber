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
          <v-card color="surface" variant="flat" class="graph-card">
            <v-card-title class="d-flex align-center">
              <v-icon icon="mdi-graph" color="accent" class="mr-2" />
              知识图谱可视化
              <v-spacer />
              <v-btn-group density="compact" class="mr-2">
                <v-btn
                  icon="mdi-magnify-plus"
                  variant="text"
                  size="small"
                  @click="zoomIn"
                />
                <v-btn
                  icon="mdi-magnify-minus"
                  variant="text"
                  size="small"
                  @click="zoomOut"
                />
                <v-btn
                  icon="mdi-fit-to-screen"
                  variant="text"
                  size="small"
                  @click="resetZoom"
                />
              </v-btn-group>
              <v-btn
                icon="mdi-refresh"
                variant="text"
                size="small"
                :loading="memoryStore.l3Loading"
                @click="loadGraph"
              />
            </v-card-title>
            <v-card-text class="pa-0">
              <div ref="graphContainer" class="graph-container">
                <svg ref="svgElement" class="graph-svg">
                  <defs>
                    <marker
                      id="arrowhead"
                      markerWidth="10"
                      markerHeight="7"
                      refX="9"
                      refY="3.5"
                      orient="auto"
                    >
                      <polygon points="0 0, 10 3.5, 0 7" fill="currentColor" class="arrow-marker" />
                    </marker>
                  </defs>
                  <g ref="mainGroup" class="main-group">
                    <g class="edges-layer"></g>
                    <g class="edge-labels-layer"></g>
                    <g class="nodes-layer"></g>
                  </g>
                </svg>
                <div v-if="memoryStore.l3Loading" class="loading-overlay">
                  <v-progress-circular indeterminate color="primary" size="64" />
                </div>
                <div v-else-if="memoryStore.l3Graph.nodes.length === 0" class="empty-overlay">
                  <v-icon icon="mdi-graph-outline" size="80" class="mb-3" />
                  <div class="text-h6">暂无图谱数据</div>
                </div>
                <div
                  v-if="selectedNode && popupPosition"
                  class="node-popup"
                  :style="{ left: popupPosition.x + 'px', top: popupPosition.y + 'px' }"
                >
                  <v-card color="surface" variant="elevated" class="popup-card">
                    <v-card-title class="d-flex align-center text-subtitle-1 pa-3">
                      <v-icon :icon="getNodeIcon(selectedNode.label)" :color="getTypeColor(selectedNode.label)" class="mr-2" size="small" />
                      {{ selectedNode.name || selectedNode.id }}
                      <v-spacer />
                      <v-btn
                        icon="mdi-close"
                        variant="text"
                        size="x-small"
                        density="compact"
                        @click="closePopup"
                      />
                    </v-card-title>
                    <v-card-text class="pa-3 pt-0">
                      <div class="text-caption mb-1">
                        <span class="text-medium-emphasis">类型：</span>{{ getNodeLabel(selectedNode.label) }}
                      </div>
                      <div class="text-caption mb-1">
                        <span class="text-medium-emphasis">ID：</span>{{ selectedNode.id }}
                      </div>
                      <div class="text-caption mb-2">
                        <span class="text-medium-emphasis">置信度：</span>{{ (selectedNode.confidence * 100).toFixed(0) }}%
                      </div>
                      <v-btn
                        color="primary"
                        size="small"
                        block
                        :loading="memoryStore.l3Loading"
                        @click="expandFromSelected"
                      >
                        <v-icon icon="mdi-arrow-expand" class="mr-1" />
                        以此节点展开
                      </v-btn>
                    </v-card-text>
                  </v-card>
                </div>
                <div
                  v-if="selectedEdge && edgePopupPosition"
                  class="node-popup"
                  :style="{ left: edgePopupPosition.x + 'px', top: edgePopupPosition.y + 'px' }"
                >
                  <v-card color="surface" variant="elevated" class="popup-card">
                    <v-card-title class="d-flex align-center text-subtitle-1 pa-3">
                      <v-icon icon="mdi-arrow-right-bold" color="secondary" class="mr-2" size="small" />
                      {{ getRelationLabel(selectedEdge.relation) }}
                      <v-spacer />
                      <v-btn
                        icon="mdi-close"
                        variant="text"
                        size="x-small"
                        density="compact"
                        @click="closeEdgePopup"
                      />
                    </v-card-title>
                    <v-card-text class="pa-3 pt-0">
                      <div class="text-caption mb-2">
                        <v-icon :icon="getNodeIcon(selectedEdge.sourceNode.label)" :color="getTypeColor(selectedEdge.sourceNode.label)" size="small" class="mr-1" />
                        <strong>{{ selectedEdge.sourceNode.name || selectedEdge.sourceNode.id }}</strong>
                      </div>
                      <div class="text-caption text-center mb-2">
                        <v-icon icon="mdi-arrow-down" size="small" />
                      </div>
                      <div class="text-caption mb-2">
                        <v-icon :icon="getNodeIcon(selectedEdge.targetNode.label)" :color="getTypeColor(selectedEdge.targetNode.label)" size="small" class="mr-1" />
                        <strong>{{ selectedEdge.targetNode.name || selectedEdge.targetNode.id }}</strong>
                      </div>
                      <v-btn
                        color="secondary"
                        size="small"
                        block
                        class="mb-2"
                        :loading="memoryStore.l3Loading"
                        @click="expandFromEdge('source')"
                      >
                        <v-icon icon="mdi-arrow-expand-left" class="mr-1" />
                        从源节点展开
                      </v-btn>
                      <v-btn
                        color="secondary"
                        size="small"
                        block
                        :loading="memoryStore.l3Loading"
                        @click="expandFromEdge('target')"
                      >
                        <v-icon icon="mdi-arrow-expand-right" class="mr-1" />
                        从目标节点展开
                      </v-btn>
                    </v-card-text>
                  </v-card>
                </div>
              </div>
            </v-card-text>
          </v-card>
        </v-col>

        <v-col cols="12" lg="4">
          <v-card color="surface" variant="flat" class="mb-4">
            <v-card-title>
              <v-icon icon="mdi-magnify" class="mr-2" />
              搜索图谱
            </v-card-title>
            <v-card-text>
              <v-text-field
                v-model="searchKeyword"
                placeholder="搜索节点或关系..."
                prepend-inner-icon="mdi-magnify"
                variant="outlined"
                density="compact"
                hide-details
                clearable
                @keyup.enter="handleSearch"
                @click:clear="clearSearch"
              />
              <v-btn
                color="primary"
                size="small"
                class="mt-2"
                block
                :loading="memoryStore.l3SearchLoading"
                @click="handleSearch"
              >
                搜索
              </v-btn>
            </v-card-text>
          </v-card>

          <v-card 
            v-if="memoryStore.l3SearchResults.nodes.length > 0 || memoryStore.l3SearchResults.edges.length > 0" 
            color="surface" 
            variant="flat" 
            class="mb-4"
          >
            <v-card-title class="d-flex align-center">
              <v-icon icon="mdi-magnify" class="mr-2" />
              搜索结果
              <v-spacer />
              <v-btn
                icon="mdi-close"
                variant="text"
                size="small"
                @click="clearSearch"
              />
            </v-card-title>
            <v-card-text>
              <div v-if="memoryStore.l3SearchResults.nodes.length > 0" class="mb-3">
                <div class="text-caption text-medium-emphasis mb-2">节点 ({{ memoryStore.l3SearchResults.nodes.length }})</div>
                <v-list density="compact" class="pa-0 bg-transparent">
                  <v-list-item
                    v-for="node in memoryStore.l3SearchResults.nodes"
                    :key="node.id"
                    :prepend-icon="getNodeIcon(node.label)"
                    @click="expandFromSearchNode(node.id)"
                  >
                    <v-list-item-title>{{ node.name || node.id }}</v-list-item-title>
                    <v-list-item-subtitle>{{ node.label }}</v-list-item-subtitle>
                    <template #append>
                      <v-chip size="x-small" :color="getTypeColor(node.label)" variant="tonal">
                        {{ (node.confidence * 100).toFixed(0) }}%
                      </v-chip>
                    </template>
                  </v-list-item>
                </v-list>
              </div>
              <div v-if="memoryStore.l3SearchResults.edges.length > 0">
                <div class="text-caption text-medium-emphasis mb-2">关系 ({{ memoryStore.l3SearchResults.edges.length }})</div>
                <v-list density="compact" class="pa-0 bg-transparent">
                  <v-list-item
                    v-for="(edge, idx) in memoryStore.l3SearchResults.edges"
                    :key="idx"
                    prepend-icon="mdi-arrow-right-bold"
                    @click="expandFromSearchEdge(edge)"
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
                  v-model="memoryStore.l3Depth"
                  :min="1"
                  :max="3"
                  :step="1"
                  thumb-label
                />
              </div>

              <div class="mb-4">
                <div class="text-caption text-medium-emphasis mb-1">最大节点数</div>
                <v-slider
                  v-model="memoryStore.l3MaxNodes"
                  :min="10"
                  :max="50"
                  :step="5"
                  thumb-label
                />
              </div>

              <div class="mb-4">
                <div class="text-caption text-medium-emphasis mb-1">起始节点</div>
                <v-chip
                  v-if="memoryStore.l3StartNode"
                  color="accent"
                  variant="tonal"
                  size="small"
                  closable
                  @click:close="clearStartNode"
                >
                  <v-icon :icon="getNodeIcon(memoryStore.l3StartNode.label)" start size="small" />
                  {{ memoryStore.l3StartNode.name || memoryStore.l3StartNode.id }}
                </v-chip>
                <span v-else class="text-medium-emphasis text-body-2">随机选择</span>
              </div>

              <v-btn
                color="primary"
                block
                :loading="memoryStore.l3Loading"
                @click="loadGraph"
              >
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
                  <div class="text-h4 font-weight-bold text-primary">{{ memoryStore.l3Graph.nodes.length }}</div>
                  <div class="text-caption text-medium-emphasis">节点</div>
                </v-col>
                <v-col cols="6" class="text-center">
                  <div class="text-h4 font-weight-bold text-secondary">{{ memoryStore.l3Graph.edges.length }}</div>
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
                  支持多跳推理和图谱可视化。点击节点或边可查看详情并从此展开图谱。使用搜索功能快速定位节点和关系。
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
              <v-card color="surface" variant="flat">
                <v-card-title class="d-flex align-center">
                  <v-icon icon="mdi-circle-multiple" color="primary" class="mr-2" />
                  节点列表
                  <v-spacer />
                  <v-text-field
                    v-model="nodesSearchKeyword"
                    placeholder="搜索节点..."
                    prepend-inner-icon="mdi-magnify"
                    variant="outlined"
                    density="compact"
                    hide-details
                    clearable
                    style="max-width: 250px"
                    @keyup.enter="handleNodesSearch"
                    @click:clear="handleNodesClearSearch"
                  />
                  <v-btn
                    v-if="selectedNodeIds.length > 0"
                    color="error"
                    variant="tonal"
                    size="small"
                    class="ml-2"
                    :loading="deletingL3Nodes"
                    @click="handleDeleteSelectedNodes"
                  >
                    <v-icon icon="mdi-delete" class="mr-1" />
                    删除选中 ({{ selectedNodeIds.length }})
                  </v-btn>
                </v-card-title>
                <v-card-text>
                  <v-progress-linear
                    v-if="memoryStore.l3NodesLoading"
                    indeterminate
                    color="primary"
                  />
                  <v-table v-else-if="memoryStore.l3Nodes.length > 0" density="compact" hover>
                    <thead>
                      <tr>
                        <th class="text-center" style="width: 40px">
                          <v-checkbox
                            :model-value="selectAllNodes"
                            density="compact"
                            hide-details
                            @update:model-value="toggleSelectAllNodes"
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
                      <tr v-for="node in memoryStore.l3Nodes" :key="node.id">
                        <td class="text-center">
                          <v-checkbox
                            :model-value="selectedNodeIds.includes(node.id)"
                            density="compact"
                            hide-details
                            @update:model-value="toggleSelectNode(node.id)"
                          />
                        </td>
                        <td class="text-caption">{{ node.id }}</td>
                        <td>{{ node.name }}</td>
                        <td>
                          <v-chip size="small" :color="getTypeColor(node.label)" variant="tonal">
                            <v-icon :icon="getNodeIcon(node.label)" start size="x-small" />
                            {{ getNodeLabel(node.label) }}
                          </v-chip>
                        </td>
                        <td>
                          <v-chip size="small" :color="getConfidenceColor(node.confidence)" variant="tonal">
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
                            @click="handleDeleteSingleNode(node.id)"
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
            </v-col>
          </v-row>
        </v-window-item>

        <v-window-item value="edges">
          <v-row>
            <v-col cols="12">
              <v-card color="surface" variant="flat">
                <v-card-title class="d-flex align-center">
                  <v-icon icon="mdi-arrow-right-bold" color="secondary" class="mr-2" />
                  关系列表
                  <v-spacer />
                  <v-text-field
                    v-model="edgesSearchKeyword"
                    placeholder="搜索关系..."
                    prepend-inner-icon="mdi-magnify"
                    variant="outlined"
                    density="compact"
                    hide-details
                    clearable
                    style="max-width: 250px"
                    @keyup.enter="handleEdgesSearch"
                    @click:clear="handleEdgesClearSearch"
                  />
                </v-card-title>
                <v-card-text>
                  <v-progress-linear
                    v-if="memoryStore.l3EdgesLoading"
                    indeterminate
                    color="primary"
                  />
                  <v-table v-else-if="memoryStore.l3Edges.length > 0" density="compact" hover>
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
                      <tr v-for="(edge, idx) in memoryStore.l3Edges" :key="idx">
                        <td>
                          <v-chip size="small" :color="getTypeColor(edge.source.label)" variant="tonal">
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
                          <v-chip size="small" :color="getTypeColor(edge.target.label)" variant="tonal">
                            <v-icon :icon="getNodeIcon(edge.target.label)" start size="x-small" />
                            {{ edge.target.name }}
                          </v-chip>
                        </td>
                        <td>
                          <v-chip size="small" :color="getConfidenceColor(edge.confidence)" variant="tonal">
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
                            @click="handleDeleteSingleEdge(edge)"
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
            </v-col>
          </v-row>
        </v-window-item>
      </v-window>
    </ComponentDisabled>

    <v-dialog v-model="l3DeleteDialog" max-width="400">
      <v-card>
        <v-card-title class="d-flex align-center">
          <v-icon icon="mdi-alert-circle" color="warning" class="mr-2" />
          确认删除
        </v-card-title>
        <v-card-text>
          {{ l3DeleteMessage }}
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="l3DeleteDialog = false">取消</v-btn>
          <v-btn color="error" variant="tonal" :loading="l3Deleting" @click="confirmL3Delete">
            确认删除
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useMemoryStore } from '@/stores'
import { useComponentState } from '@/composables/useComponentState'
import ComponentDisabled from '@/components/ComponentDisabled.vue'
import type { KGNode, KGEdge, L3EdgeDetail } from '@/types'

const memoryStore = useMemoryStore()
const { status, error, errorType, refreshState } = useComponentState('l3_kg')

const activeTab = ref('graph')

const graphContainer = ref<HTMLElement | null>(null)
const svgElement = ref<SVGSVGElement | null>(null)
const mainGroup = ref<SVGGElement | null>(null)

const selectedNode = ref<KGNode | null>(null)
const popupPosition = ref<{ x: number; y: number } | null>(null)

const selectedEdge = ref<{
  source: string
  target: string
  relation: string
  sourceNode: KGNode
  targetNode: KGNode
} | null>(null)
const edgePopupPosition = ref<{ x: number; y: number } | null>(null)

const searchKeyword = ref('')

const currentZoom = ref(1)
const currentTranslate = ref({ x: 0, y: 0 })

const nodesSearchKeyword = ref('')
const edgesSearchKeyword = ref('')
const selectedNodeIds = ref<string[]>([])
const selectAllNodes = ref(false)
const deletingL3Nodes = ref(false)

const l3DeleteDialog = ref(false)
const l3Deleting = ref(false)
const l3DeleteMessage = ref('')
const l3DeleteAction = ref<() => Promise<void>>(async () => {})

const getConfidenceColor = (confidence: number): string => {
  if (confidence >= 0.9) return 'success'
  if (confidence >= 0.7) return 'info'
  if (confidence >= 0.5) return 'warning'
  return 'error'
}

const formatTime = (timestamp?: string): string => {
  if (!timestamp) return '-'
  try {
    const date = new Date(timestamp)
    return date.toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit'
    })
  } catch {
    return timestamp
  }
}

const handleNodesSearch = () => {
  memoryStore.fetchL3Nodes(nodesSearchKeyword.value || undefined)
}

const handleNodesClearSearch = () => {
  nodesSearchKeyword.value = ''
  memoryStore.fetchL3Nodes()
}

const handleEdgesSearch = () => {
  memoryStore.fetchL3Edges(edgesSearchKeyword.value || undefined)
}

const handleEdgesClearSearch = () => {
  edgesSearchKeyword.value = ''
  memoryStore.fetchL3Edges()
}

const toggleSelectNode = (id: string) => {
  const idx = selectedNodeIds.value.indexOf(id)
  if (idx >= 0) {
    selectedNodeIds.value.splice(idx, 1)
  } else {
    selectedNodeIds.value.push(id)
  }
}

const toggleSelectAllNodes = (checked: boolean | null) => {
  if (checked) {
    selectedNodeIds.value = memoryStore.l3Nodes.map(n => n.id)
  } else {
    selectedNodeIds.value = []
  }
}

const handleDeleteSingleNode = (id: string) => {
  l3DeleteMessage.value = '确定要删除该节点吗？与之关联的关系也将被删除。此操作不可撤销。'
  l3DeleteAction.value = async () => {
    await memoryStore.deleteL3Nodes([id])
    selectedNodeIds.value = selectedNodeIds.value.filter(nid => nid !== id)
  }
  l3DeleteDialog.value = true
}

const handleDeleteSelectedNodes = () => {
  l3DeleteMessage.value = `确定要删除 ${selectedNodeIds.value.length} 个节点吗？与之关联的关系也将被删除。此操作不可撤销。`
  l3DeleteAction.value = async () => {
    await memoryStore.deleteL3Nodes(selectedNodeIds.value)
    selectedNodeIds.value = []
  }
  l3DeleteDialog.value = true
}

const handleDeleteSingleEdge = (edge: L3EdgeDetail) => {
  l3DeleteMessage.value = `确定要删除关系「${edge.source.name} → ${getRelationLabel(edge.relation)} → ${edge.target.name}」吗？此操作不可撤销。`
  l3DeleteAction.value = async () => {
    await memoryStore.deleteL3Edge(edge.source.id, edge.target.id, edge.relation)
  }
  l3DeleteDialog.value = true
}

const confirmL3Delete = async () => {
  l3Deleting.value = true
  try {
    await l3DeleteAction.value()
    l3DeleteDialog.value = false
  } catch (error) {
    console.error('删除失败:', error)
  } finally {
    l3Deleting.value = false
  }
}

const nodeTypeStats = computed(() => {
  const stats: Record<string, number> = {}
  memoryStore.l3Graph.nodes.forEach(node => {
    stats[node.label] = (stats[node.label] || 0) + 1
  })
  return stats
})

const relationTypeStats = computed(() => {
  const stats: Record<string, number> = {}
  memoryStore.l3Graph.edges.forEach(edge => {
    stats[edge.relation] = (stats[edge.relation] || 0) + 1
  })
  return stats
})

const loadGraph = () => {
  memoryStore.fetchL3Graph()
}

const clearStartNode = () => {
  memoryStore.fetchL3Graph()
}

const closePopup = () => {
  selectedNode.value = null
  popupPosition.value = null
}

const closeEdgePopup = () => {
  selectedEdge.value = null
  edgePopupPosition.value = null
}

const expandFromSelected = () => {
  if (selectedNode.value) {
    memoryStore.expandFromNode(selectedNode.value.id)
    closePopup()
  }
}

const expandFromEdge = (type: 'source' | 'target') => {
  if (selectedEdge.value) {
    const nodeId = type === 'source' ? selectedEdge.value.source : selectedEdge.value.target
    memoryStore.expandFromNode(nodeId)
    closeEdgePopup()
  }
}

const handleSearch = () => {
  if (searchKeyword.value.trim()) {
    memoryStore.searchL3(searchKeyword.value.trim())
  }
}

const clearSearch = () => {
  searchKeyword.value = ''
  memoryStore.clearL3Search()
}

const expandFromSearchNode = (nodeId: string) => {
  memoryStore.expandFromNode(nodeId)
}

const expandFromSearchEdge = (edge: { source: { id: string }, target: { id: string } }) => {
  memoryStore.expandFromNode(edge.source.id)
}

const getNodeIcon = (label: string): string => {
  const icons: Record<string, string> = {
    Person: 'mdi-account',
    Preference: 'mdi-heart',
    Skill: 'mdi-tools',
    Trait: 'mdi-emoticon',
    Goal: 'mdi-flag',
    Belief: 'mdi-lightbulb-on',
    Event: 'mdi-calendar',
    Concept: 'mdi-lightbulb',
    Location: 'mdi-map-marker',
    Item: 'mdi-package-variant',
    Topic: 'mdi-tag',
    Group: 'mdi-account-group',
    Entity: 'mdi-circle'
  }
  return icons[label] || 'mdi-tag'
}

const getTypeColor = (label: string): string => {
  const colors: Record<string, string> = {
    Person: 'primary',
    Preference: 'pink',
    Skill: 'teal',
    Trait: 'purple',
    Goal: 'orange',
    Belief: 'indigo',
    Event: 'secondary',
    Concept: 'info',
    Location: 'success',
    Item: 'warning',
    Topic: 'accent',
    Group: 'cyan',
    Entity: 'default'
  }
  return colors[label] || 'default'
}

const NODE_TYPE_LABELS: Record<string, string> = {
  Person: '人物',
  Preference: '偏好',
  Skill: '技能',
  Trait: '性格特征',
  Goal: '目标',
  Belief: '信念',
  Event: '事件',
  Concept: '概念',
  Location: '地点',
  Item: '物品',
  Topic: '话题',
  Group: '群体'
}

const RELATION_TYPE_LABELS: Record<string, string> = {
  KNOWS: '认识',
  HAS_PREFERENCE: '偏好',
  HAS_SKILL: '掌握',
  HAS_TRAIT: '具有',
  HAS_GOAL: '追求',
  HAS_BELIEF: '相信',
  PARTICIPATED_IN: '参与',
  LOCATED_AT: '位于',
  HAPPENED_AT: '发生在',
  PART_OF: '属于',
  LEADS_TO: '导致',
  CONTRADICTS: '矛盾',
  SUPPORTS: '支持',
  RELATED_TO: '相关'
}

const getNodeLabel = (label: string): string => NODE_TYPE_LABELS[label] || label
const getRelationLabel = (relation: string): string => RELATION_TYPE_LABELS[relation] || relation

const zoomIn = () => {
  currentZoom.value = Math.min(currentZoom.value * 1.2, 3)
  updateTransform()
}

const zoomOut = () => {
  currentZoom.value = Math.max(currentZoom.value / 1.2, 0.3)
  updateTransform()
}

const resetZoom = () => {
  currentZoom.value = 1
  currentTranslate.value = { x: 0, y: 0 }
  updateTransform()
}

const updateTransform = () => {
  if (mainGroup.value) {
    mainGroup.value.setAttribute(
      'transform',
      `translate(${currentTranslate.value.x}, ${currentTranslate.value.y}) scale(${currentZoom.value})`
    )
  }
}

const renderGraph = () => {
  if (!svgElement.value || !mainGroup.value) return

  const nodes = memoryStore.l3Graph.nodes
  const edges = memoryStore.l3Graph.edges

  if (nodes.length === 0) return

  const container = graphContainer.value
  if (!container) return

  const width = container.clientWidth
  const height = 500

  svgElement.value.setAttribute('width', String(width))
  svgElement.value.setAttribute('height', String(height))

  const nodeMap = new Map<string, KGNode>()
  nodes.forEach(n => nodeMap.set(n.id, n))

  const nodePositions = new Map<string, { x: number; y: number }>()
  const centerX = width / 2
  const centerY = height / 2
  const radius = Math.min(width, height) / 3

  nodes.forEach((node, i) => {
    const angle = (2 * Math.PI * i) / nodes.length
    nodePositions.set(node.id, {
      x: centerX + radius * Math.cos(angle),
      y: centerY + radius * Math.sin(angle)
    })
  })

  const edgesLayer = mainGroup.value.querySelector('.edges-layer') as SVGGElement
  const edgeLabelsLayer = mainGroup.value.querySelector('.edge-labels-layer') as SVGGElement
  const nodesLayer = mainGroup.value.querySelector('.nodes-layer') as SVGGElement

  edgesLayer.innerHTML = ''
  edgeLabelsLayer.innerHTML = ''
  nodesLayer.innerHTML = ''

  edges.forEach(edge => {
    const source = nodePositions.get(edge.source)
    const target = nodePositions.get(edge.target)

    if (!source || !target) return

    const midX = (source.x + target.x) / 2
    const midY = (source.y + target.y) / 2

    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line')
    line.setAttribute('x1', String(source.x))
    line.setAttribute('y1', String(source.y))
    line.setAttribute('x2', String(target.x))
    line.setAttribute('y2', String(target.y))
    line.setAttribute('stroke', 'currentColor')
    line.setAttribute('stroke-width', '1.5')
    line.setAttribute('stroke-opacity', '0.5')
    line.setAttribute('marker-end', 'url(#arrowhead)')
    line.classList.add('graph-edge')
    line.style.cursor = 'pointer'

    const sourceNode = nodeMap.get(edge.source)
    const targetNode = nodeMap.get(edge.target)

    line.addEventListener('click', (event: MouseEvent) => {
      if (sourceNode && targetNode) {
        selectedEdge.value = {
          source: edge.source,
          target: edge.target,
          relation: edge.relation,
          sourceNode,
          targetNode
        }
        const containerRect = graphContainer.value?.getBoundingClientRect()
        if (containerRect) {
          edgePopupPosition.value = {
            x: event.clientX - containerRect.left + 10,
            y: event.clientY - containerRect.top + 10
          }
        }
      }
      event.stopPropagation()
    })

    line.addEventListener('mouseenter', () => {
      line.setAttribute('stroke-opacity', '1')
      line.setAttribute('stroke-width', '2.5')
    })

    line.addEventListener('mouseleave', () => {
      line.setAttribute('stroke-opacity', '0.5')
      line.setAttribute('stroke-width', '1.5')
    })

    edgesLayer.appendChild(line)

    const labelText = document.createElementNS('http://www.w3.org/2000/svg', 'text')
    
    labelText.setAttribute('x', String(midX))
    labelText.setAttribute('y', String(midY))
    labelText.setAttribute('text-anchor', 'middle')
    labelText.setAttribute('dominant-baseline', 'middle')
    labelText.setAttribute('fill', 'currentColor')
    labelText.setAttribute('font-size', '10')
    labelText.setAttribute('font-weight', '500')
    labelText.textContent = getRelationLabel(edge.relation)
    labelText.style.pointerEvents = 'none'

    edgesLayer.appendChild(labelText)
  })

  nodes.forEach(node => {
    const pos = nodePositions.get(node.id)
    if (!pos) return

    const g = document.createElementNS('http://www.w3.org/2000/svg', 'g')
    g.classList.add('graph-node')
    g.style.cursor = 'pointer'

    const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle')
    circle.setAttribute('cx', String(pos.x))
    circle.setAttribute('cy', String(pos.y))
    circle.setAttribute('r', '20')
    circle.setAttribute('fill', `rgb(var(--v-theme-${getTypeColor(node.label)}))`)
    circle.setAttribute('stroke', 'currentColor')
    circle.setAttribute('stroke-width', '2')

    const text = document.createElementNS('http://www.w3.org/2000/svg', 'text')
    text.setAttribute('x', String(pos.x))
    text.setAttribute('y', String(pos.y + 35))
    text.setAttribute('text-anchor', 'middle')
    text.setAttribute('fill', 'currentColor')
    text.setAttribute('font-size', '12')
    text.textContent = node.name || node.id

    g.appendChild(circle)
    g.appendChild(text)

    g.addEventListener('click', (event: MouseEvent) => {
      selectedNode.value = node
      closeEdgePopup()
      const containerRect = graphContainer.value?.getBoundingClientRect()
      if (containerRect) {
        popupPosition.value = {
          x: event.clientX - containerRect.left + 10,
          y: event.clientY - containerRect.top + 10
        }
      }
    })

    g.addEventListener('mouseenter', () => {
      circle.setAttribute('r', '25')
    })

    g.addEventListener('mouseleave', () => {
      circle.setAttribute('r', '20')
    })

    nodesLayer.appendChild(g)
  })
}

watch(() => memoryStore.l3Graph, () => {
  nextTick(() => {
    renderGraph()
  })
}, { deep: true })

watch(activeTab, (newTab) => {
  if (newTab === 'nodes' && memoryStore.l3Nodes.length === 0) {
    memoryStore.fetchL3Nodes()
  } else if (newTab === 'edges' && memoryStore.l3Edges.length === 0) {
    memoryStore.fetchL3Edges()
  }
})

const handleRefresh = () => {
  if (activeTab.value === 'graph') {
    loadGraph()
  } else if (activeTab.value === 'nodes') {
    memoryStore.fetchL3Nodes(nodesSearchKeyword.value || undefined)
  } else if (activeTab.value === 'edges') {
    memoryStore.fetchL3Edges(edgesSearchKeyword.value || undefined)
  }
}

onMounted(() => {
  loadGraph()
  window.addEventListener('iris:refresh', handleRefresh)
  window.addEventListener('resize', renderGraph)
})

onUnmounted(() => {
  window.removeEventListener('iris:refresh', handleRefresh)
  window.removeEventListener('resize', renderGraph)
})
</script>

<style scoped>
.graph-card {
  min-height: 600px;
}

.graph-container {
  position: relative;
  width: 100%;
  height: 500px;
  background: rgb(var(--v-theme-surface-variant));
  border-radius: 8px;
  overflow: hidden;
}

.graph-svg {
  width: 100%;
  height: 100%;
}

.main-group {
  transition: transform 0.2s ease;
}

.graph-node circle {
  transition: r 0.2s ease;
}

.graph-edge {
  transition: stroke-opacity 0.2s ease, stroke-width 0.2s ease;
}

.arrow-marker {
  fill: rgb(var(--v-theme-on-surface));
  opacity: 0.5;
}

.loading-overlay,
.empty-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: rgb(var(--v-theme-surface));
  opacity: 0.9;
}

.node-popup {
  position: absolute;
  z-index: 100;
  pointer-events: auto;
  min-width: 200px;
  max-width: 280px;
}

.popup-card {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
}
</style>
