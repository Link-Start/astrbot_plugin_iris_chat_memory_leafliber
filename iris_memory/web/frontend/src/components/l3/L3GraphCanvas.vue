<template>
  <v-card color="surface" variant="flat" class="graph-card">
    <v-card-title class="d-flex align-center">
      <v-icon icon="mdi-graph" color="accent" class="mr-2" />
      知识图谱可视化
      <v-spacer />
      <v-btn-group density="compact" class="mr-2">
        <v-btn icon="mdi-magnify-plus" variant="text" size="small" @click="zoomIn" />
        <v-btn icon="mdi-magnify-minus" variant="text" size="small" @click="zoomOut" />
        <v-btn icon="mdi-fit-to-screen" variant="text" size="small" @click="fitView" />
      </v-btn-group>
      <v-btn
        icon="mdi-refresh"
        variant="text"
        size="small"
        :loading="loading"
        @click="emit('reload')"
      />
    </v-card-title>
    <v-card-text class="pa-0">
      <div ref="containerRef" class="graph-container">
        <div v-if="loading" class="loading-overlay">
          <v-progress-circular indeterminate color="primary" size="64" />
        </div>
        <div v-else-if="nodes.length === 0" class="empty-overlay">
          <v-icon icon="mdi-graph-outline" size="80" class="mb-3" />
          <div class="text-h6">暂无图谱数据</div>
        </div>

        <!-- 节点详情弹窗 -->
        <div
          v-if="selectedNode && popupPos"
          class="node-popup"
          :style="{ left: popupPos.x + 'px', top: popupPos.y + 'px' }"
        >
          <v-card color="surface" variant="elevated" class="popup-card">
            <v-card-title class="d-flex align-center text-subtitle-1 pa-3">
              <v-icon
                :icon="getNodeIcon(selectedNode.label)"
                :color="getTypeColor(selectedNode.label)"
                class="mr-2"
                size="small"
              />
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
                :loading="loading"
                @click="expandSelected"
              >
                <v-icon icon="mdi-arrow-expand" class="mr-1" />
                以此节点展开
              </v-btn>
            </v-card-text>
          </v-card>
        </div>

        <!-- 关系详情弹窗 -->
        <div
          v-if="selectedEdge && edgePopupPos"
          class="node-popup"
          :style="{ left: edgePopupPos.x + 'px', top: edgePopupPos.y + 'px' }"
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
                <v-icon
                  :icon="getNodeIcon(selectedEdge.sourceNode.label)"
                  :color="getTypeColor(selectedEdge.sourceNode.label)"
                  size="small"
                  class="mr-1"
                />
                <strong>{{ selectedEdge.sourceNode.name || selectedEdge.sourceNode.id }}</strong>
              </div>
              <div class="text-caption text-center mb-2">
                <v-icon icon="mdi-arrow-down" size="small" />
              </div>
              <div class="text-caption mb-2">
                <v-icon
                  :icon="getNodeIcon(selectedEdge.targetNode.label)"
                  :color="getTypeColor(selectedEdge.targetNode.label)"
                  size="small"
                  class="mr-1"
                />
                <strong>{{ selectedEdge.targetNode.name || selectedEdge.targetNode.id }}</strong>
              </div>
              <v-btn
                color="secondary"
                size="small"
                block
                class="mb-2"
                :loading="loading"
                @click="expandEdge('source')"
              >
                <v-icon icon="mdi-arrow-expand-left" class="mr-1" />
                从源节点展开
              </v-btn>
              <v-btn
                color="secondary"
                size="small"
                block
                :loading="loading"
                @click="expandEdge('target')"
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
</template>

<script setup lang="ts">
import { ref, shallowRef, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { Graph } from '@antv/g6'
import type { GraphData, NodeData, EdgeData } from '@antv/g6'
import type { KGNode, KGEdge } from '@/types'
import {
  getNodeIcon,
  getTypeColor,
  getNodeLabel,
  getRelationLabel,
  resolveThemeColor,
} from '@/composables/l3Constants'

interface SelectedEdgeInfo {
  source: string
  target: string
  relation: string
  sourceNode: KGNode
  targetNode: KGNode
}

const props = defineProps<{
  nodes: KGNode[]
  edges: KGEdge[]
  loading: boolean
}>()

const emit = defineEmits<{
  reload: []
  'expand-node': [nodeId: string]
}>()

const containerRef = ref<HTMLElement | null>(null)
// G6 实例用 shallowRef 避免被 Vue 深度代理（性能与正确性都需要）
const graphRef = shallowRef<Graph | null>(null)

const selectedNode = ref<KGNode | null>(null)
const popupPos = ref<{ x: number; y: number } | null>(null)
const selectedEdge = ref<SelectedEdgeInfo | null>(null)
const edgePopupPos = ref<{ x: number; y: number } | null>(null)

let resizeObserver: ResizeObserver | null = null

// ---- 颜色解析：从 Vuetify 主题变量读取实际 rgb 值（canvas 无法消费 CSS 变量）----
const colorCache = new Map<string, string>()
const nodeFill = (label: string): string => {
  if (!colorCache.has(label)) {
    colorCache.set(label, resolveThemeColor(getTypeColor(label), '#5c6bc0'))
  }
  return colorCache.get(label)!
}

// ---- G6 数据转换 ----
const toGraphData = (): GraphData => ({
  nodes: props.nodes.map<NodeData>((n) => ({
    id: n.id,
    data: { label: n.label, name: n.name, confidence: n.confidence },
  })),
  edges: props.edges.map<EdgeData>((e) => ({
    source: e.source,
    target: e.target,
    data: { relation: e.relation },
  })),
})

// ---- 初始化 G6 ----
const initGraph = () => {
  const container = containerRef.value
  if (!container) return
  const width = container.clientWidth || 800
  const height = container.clientHeight || 500

  const graph = new Graph({
    container,
    width,
    height,
    autoFit: 'view',
    data: toGraphData(),
    layout: {
      type: 'force',
      preventOverlap: true,
      nodeSize: 36,
      linkDistance: 140,
      nodeStrength: -60,
      edgeStrength: 0.7,
      gravity: 8,
      alpha: 0.3,
      alphaDecay: 0.028,
      alphaMin: 0.001,
    },
    node: {
      type: 'circle',
      style: (d: NodeData) => {
        const label = (d.data?.label as string) || 'Entity'
        const name = (d.data?.name as string) || String(d.id)
        return {
          size: 32,
          fill: nodeFill(label),
          stroke: '#ffffff',
          lineWidth: 2,
          labelText: name,
          labelPlacement: 'bottom',
          labelFontSize: 12,
          labelFill: '#424242',
          labelBackground: true,
          labelBackgroundFill: 'rgba(255,255,255,0.85)',
          labelBackgroundOpacity: 0.9,
          labelPadding: [2, 4],
          cursor: 'pointer',
        }
      },
      state: {
        active: {
          lineWidth: 3,
          stroke: '#ff9800',
          shadowColor: 'rgba(255,152,0,0.6)',
          shadowBlur: 12,
        },
        inactive: { opacity: 0.25 },
        selected: { lineWidth: 3, stroke: '#ff9800' },
      },
    },
    edge: {
      type: 'line',
      style: (d: EdgeData) => ({
        stroke: '#9e9e9e',
        lineWidth: 1.5,
        strokeOpacity: 0.7,
        endArrow: true,
        labelText: getRelationLabel((d.data?.relation as string) || ''),
        labelFontSize: 10,
        labelFill: '#616161',
        labelBackground: true,
        labelBackgroundFill: 'rgba(255,255,255,0.85)',
        labelBackgroundOpacity: 0.9,
        labelPadding: [1, 3],
        cursor: 'pointer',
      }),
      state: {
        active: { stroke: '#ff9800', lineWidth: 2.5, strokeOpacity: 1 },
        inactive: { opacity: 0.15 },
      },
    },
    behaviors: [
      'zoom-canvas',
      'drag-canvas',
      'drag-element',
      {
        type: 'hover-activate',
        degree: 1,
        state: 'active',
        inactiveState: 'inactive',
      },
    ],
  })

  // 节点点击：弹出详情
  graph.on('node:click', (evt: any) => {
    const id = evt.target?.id as string | undefined
    if (!id) return
    const node = props.nodes.find((n) => n.id === id)
    if (!node) return
    selectedEdge.value = null
    edgePopupPos.value = null
    selectedNode.value = node
    popupPos.value = toContainerPos(evt)
    // 同时设置选中态
    clearStates()
    graph.setElementState(id, 'selected')
  })

  // 边点击：弹出关系详情
  graph.on('edge:click', (evt: any) => {
    const id = evt.target?.id as string | undefined
    if (!id) return
    const edgeData = graph.getEdgeData(id)
    const sourceId = edgeData?.source as string
    const targetId = edgeData?.target as string
    const relation = (edgeData?.data?.relation as string) || ''
    const sourceNode = props.nodes.find((n) => n.id === sourceId)
    const targetNode = props.nodes.find((n) => n.id === targetId)
    if (!sourceNode || !targetNode) return
    selectedNode.value = null
    popupPos.value = null
    selectedEdge.value = {
      source: sourceId,
      target: targetId,
      relation,
      sourceNode,
      targetNode,
    }
    edgePopupPos.value = toContainerPos(evt)
  })

  // 点击画布空白：关闭弹窗
  graph.on('canvas:click', () => {
    closePopup()
    closeEdgePopup()
    clearStates()
  })

  graphRef.value = graph
  graph.render().catch((e) => console.error('G6 render failed:', e))
}

const toContainerPos = (evt: any): { x: number; y: number } => {
  const rect = containerRef.value?.getBoundingClientRect()
  const x = evt.clientX ?? (evt.detail?.x ?? 0)
  const y = evt.clientY ?? (evt.detail?.y ?? 0)
  if (!rect) return { x, y }
  return { x: x - rect.left + 12, y: y - rect.top + 12 }
}

const clearStates = () => {
  const graph = graphRef.value
  if (!graph) return
  try {
    graph.getNodeData().forEach((n) => {
      if (graph.getElementState(n.id).includes('selected')) {
        graph.setElementState(n.id, [])
      }
    })
  } catch {
    // ignore
  }
}

// ---- 数据更新 ----
const updateData = async () => {
  const graph = graphRef.value
  if (!graph) return
  closePopup()
  closeEdgePopup()
  graph.setData(toGraphData())
  try {
    await graph.render()
  } catch (e) {
    console.error('G6 update failed:', e)
  }
}

watch(
  () => [props.nodes, props.edges],
  () => {
    nextTick(() => updateData())
  },
  { deep: true }
)

// ---- 工具栏 ----
const zoomIn = () => {
  const graph = graphRef.value
  if (!graph) return
  const cur = graph.getZoom?.() ?? 1
  graph.zoomTo(Math.min(cur * 1.2, 3)).catch(() => {})
}

const zoomOut = () => {
  const graph = graphRef.value
  if (!graph) return
  const cur = graph.getZoom?.() ?? 1
  graph.zoomTo(Math.max(cur / 1.2, 0.3)).catch(() => {})
}

const fitView = () => {
  graphRef.value?.fitView({ when: 'always' }).catch(() => {})
}

// ---- 弹窗操作 ----
const closePopup = () => {
  selectedNode.value = null
  popupPos.value = null
}

const closeEdgePopup = () => {
  selectedEdge.value = null
  edgePopupPos.value = null
}

const expandSelected = () => {
  if (selectedNode.value) {
    emit('expand-node', selectedNode.value.id)
    closePopup()
  }
}

const expandEdge = (which: 'source' | 'target') => {
  if (!selectedEdge.value) return
  const id = which === 'source' ? selectedEdge.value.source : selectedEdge.value.target
  emit('expand-node', id)
  closeEdgePopup()
}

// ---- 暴露给父组件：聚焦节点 ----
const focusNode = async (nodeId: string) => {
  const graph = graphRef.value
  if (!graph) return
  if (graph.hasNode(nodeId)) {
    closePopup()
    closeEdgePopup()
    clearStates()
    graph.setElementState(nodeId, 'selected')
    await graph.focusElement(nodeId).catch(() => {})
  } else {
    // 节点不在当前视图中，触发以该节点为中心重新加载
    emit('expand-node', nodeId)
  }
}

defineExpose({ focusNode })

// ---- 生命周期 ----
const handleResize = () => {
  const graph = graphRef.value
  const container = containerRef.value
  if (!graph || !container) return
  graph.setSize(container.clientWidth, container.clientHeight)
}

onMounted(() => {
  initGraph()
  resizeObserver = new ResizeObserver(() => handleResize())
  if (containerRef.value) resizeObserver.observe(containerRef.value)
})

onUnmounted(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
  graphRef.value?.destroy()
  graphRef.value = null
})
</script>

<style scoped>
.graph-card {
  min-height: 600px;
}

.graph-container {
  position: relative;
  width: 100%;
  height: 540px;
  background: rgb(var(--v-theme-surface-variant));
  border-radius: 8px;
  overflow: hidden;
}

.loading-overlay,
.empty-overlay {
  position: absolute;
  inset: 0;
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
  min-width: 220px;
  max-width: 300px;
}
</style>
