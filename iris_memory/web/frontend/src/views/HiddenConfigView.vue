<template>
  <div class="hidden-config-view">
    <v-row>
      <v-col cols="12">
        <v-card color="surface" variant="flat">
          <v-card-title class="d-flex align-center">
            <v-icon icon="mdi-cog-outline" color="primary" class="mr-2" />
            隐藏参数配置
            <v-spacer />
            <v-btn
              color="primary"
              variant="tonal"
              size="small"
              prepend-icon="mdi-refresh"
              :loading="loading"
              @click="loadData"
            >
              刷新
            </v-btn>
          </v-card-title>
          <v-card-text>
            <v-alert type="warning" variant="tonal" density="compact" class="mb-4">
              <div class="text-body-2">
                这些参数控制内部行为，修改后立即生效并自动持久化。不当修改可能导致功能异常，请谨慎操作。
                此页面仅管理隐藏参数，不涉及 AstrBot WebUI 中的显性配置。
              </div>
            </v-alert>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <v-row class="mt-2">
      <v-col cols="12">
        <v-card color="surface" variant="flat">
          <v-card-title class="d-flex align-center">
            <v-icon icon="mdi-backup-restore" color="warning" class="mr-2" />
            批量操作
          </v-card-title>
          <v-card-text>
            <div class="d-flex ga-3 flex-wrap">
              <v-btn
                color="primary"
                variant="tonal"
                prepend-icon="mdi-content-save"
                :loading="saving"
                :disabled="!hasChanges"
                @click="handleSaveAll"
              >
                保存修改 ({{ changedKeys.length }})
              </v-btn>
              <v-btn
                color="grey"
                variant="tonal"
                prepend-icon="mdi-undo"
                :disabled="!hasChanges"
                @click="handleDiscardChanges"
              >
                放弃修改
              </v-btn>
              <v-btn
                color="error"
                variant="tonal"
                prepend-icon="mdi-restore"
                :loading="resetting"
                @click="handleResetAll"
              >
                全部重置为默认值
              </v-btn>
            </div>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <v-row v-if="loading" class="mt-4">
      <v-col cols="12" class="text-center py-8">
        <v-progress-circular indeterminate color="primary" size="48" />
      </v-col>
    </v-row>

    <template v-else>
      <v-row
        v-for="group in groupsWithItems"
        :key="group.name"
        class="mt-2"
      >
        <v-col cols="12">
          <v-card color="surface" variant="flat">
            <v-card-title class="d-flex align-center text-subtitle-1">
              <v-icon :icon="getGroupIcon(group.name)" color="primary" class="mr-2" size="20" />
              {{ group.name }}
              <v-chip size="x-small" variant="tonal" color="primary" class="ml-2">
                {{ group.items.length }}
              </v-chip>
            </v-card-title>
            <v-card-text>
              <v-table density="compact" class="bg-transparent">
                <thead>
                  <tr>
                    <th style="width: 25%">参数名</th>
                    <th style="width: 15%">当前值</th>
                    <th style="width: 15%">默认值</th>
                    <th style="width: 35%">说明</th>
                    <th style="width: 10%">操作</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="item in group.items"
                    :key="item.key"
                    :class="{ 'changed-row': isChanged(item.key) }"
                  >
                    <td>
                      <code class="text-body-2">{{ item.key }}</code>
                    </td>
                    <td>
                      <template v-if="editingKey === item.key">
                        <v-select
                          v-if="item.type === 'literal' && item.options.length > 0"
                          v-model="editValue"
                          :items="item.options"
                          density="compact"
                          variant="outlined"
                          hide-details
                          autofocus
                          @update:model-value="confirmEdit(item)"
                          @blur="cancelEdit"
                        />
                        <v-switch
                          v-else-if="item.type === 'bool'"
                          v-model="editValue"
                          density="compact"
                          color="primary"
                          hide-details
                          @update:model-value="confirmEdit(item)"
                        />
                        <v-text-field
                          v-else
                          v-model="editValue"
                          :type="item.type === 'int' || item.type === 'float' ? 'number' : 'text'"
                          density="compact"
                          variant="outlined"
                          hide-details
                          autofocus
                          @keydown.enter="confirmEdit(item)"
                          @keydown.escape="cancelEdit"
                          @blur="confirmEdit(item)"
                        />
                      </template>
                      <template v-else>
                        <v-chip
                          size="small"
                          :color="isChanged(item.key) ? 'warning' : 'default'"
                          :variant="isChanged(item.key) ? 'tonal' : 'text'"
                          class="cursor-pointer"
                          @click="startEdit(item)"
                        >
                          {{ formatValue(item) }}
                        </v-chip>
                      </template>
                    </td>
                    <td>
                      <span class="text-medium-emphasis text-body-2">{{ formatDefaultValue(item) }}</span>
                    </td>
                    <td>
                      <span class="text-body-2">{{ item.description }}</span>
                    </td>
                    <td>
                      <v-btn
                        v-if="isChanged(item.key)"
                        icon="mdi-undo"
                        variant="text"
                        size="x-small"
                        color="warning"
                        @click="handleResetItem(item)"
                      />
                    </td>
                  </tr>
                </tbody>
              </v-table>
            </v-card-text>
          </v-card>
        </v-col>
      </v-row>
    </template>

    <v-dialog v-model="confirmDialog" max-width="400">
      <v-card>
        <v-card-title class="d-flex align-center">
          <v-icon icon="mdi-alert" color="warning" class="mr-2" />
          确认操作
        </v-card-title>
        <v-card-text>{{ confirmMessage }}</v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="confirmDialog = false">取消</v-btn>
          <v-btn color="error" variant="tonal" @click="confirmAction">确认</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-snackbar
      v-model="showSnackbar"
      :color="snackbarColor"
      :timeout="4000"
      location="top"
    >
      {{ snackbarText }}
    </v-snackbar>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import {
  getHiddenConfig,
  updateHiddenConfig,
  deleteHiddenConfig,
  resetHiddenConfig,
  type HiddenConfigItem,
  type HiddenConfigGroup
} from '@/api/hiddenConfig'

const loading = ref(false)
const saving = ref(false)
const resetting = ref(false)

const items = ref<HiddenConfigItem[]>([])
const groups = ref<HiddenConfigGroup[]>([])

const pendingChanges = ref<Record<string, unknown>>({})

const editingKey = ref<string | null>(null)
const editValue = ref<string | number | boolean | null>(null)

const confirmDialog = ref(false)
const confirmMessage = ref('')
const confirmCallback = ref<(() => void) | null>(null)

const showSnackbar = ref(false)
const snackbarText = ref('')
const snackbarColor = ref('success')

const changedKeys = computed(() => Object.keys(pendingChanges.value))

const hasChanges = computed(() => changedKeys.value.length > 0)

const groupsWithItems = computed(() => {
  return groups.value.map(group => ({
    ...group,
    items: items.value.filter(item => item.group === group.name)
  })).filter(group => group.items.length > 0)
})

const isChanged = (key: string): boolean => {
  return key in pendingChanges.value
}

const getCurrentValue = (item: HiddenConfigItem): unknown => {
  if (item.key in pendingChanges.value) {
    return pendingChanges.value[item.key]
  }
  return item.value
}

const formatValue = (item: HiddenConfigItem): string => {
  const val = getCurrentValue(item)
  if (typeof val === 'boolean') return val ? 'true' : 'false'
  if (val === null || val === undefined) return '(空)'
  return String(val)
}

const formatDefaultValue = (item: HiddenConfigItem): string => {
  const val = item.default
  if (typeof val === 'boolean') return val ? 'true' : 'false'
  if (val === null || val === undefined) return '(空)'
  return String(val)
}

const getGroupIcon = (name: string): string => {
  const icons: Record<string, string> = {
    'Token 预算': 'mdi-counter',
    '遗忘算法': 'mdi-delete-clock',
    '调试配置': 'mdi-bug',
    '性能调优': 'mdi-speedometer',
    'L3 知识图谱': 'mdi-graph',
    'LLM 调用管理': 'mdi-robot',
    '定时任务': 'mdi-clock-outline',
    '知识图谱提取任务': 'mdi-graph-outline',
    'Tool 配置': 'mdi-tools',
    'Web 安全': 'mdi-shield-lock',
    '画像系统': 'mdi-account-group',
    '图片解析': 'mdi-image-search',
    '输入清理': 'mdi-filter',
    '遗忘确认': 'mdi-check-decagram',
    'L2 查询改写': 'mdi-text-search'
  }
  return icons[name] || 'mdi-cog'
}

const startEdit = (item: HiddenConfigItem) => {
  editingKey.value = item.key
  const val = getCurrentValue(item)
  editValue.value = typeof val === 'boolean' ? val : String(val)
}

const confirmEdit = (item: HiddenConfigItem) => {
  if (editingKey.value !== item.key) return

  let newValue = editValue.value

  if (item.type === 'int') {
    newValue = parseInt(String(newValue), 10)
    if (isNaN(newValue as number)) {
      cancelEdit()
      return
    }
  } else if (item.type === 'float') {
    newValue = parseFloat(String(newValue))
    if (isNaN(newValue as number)) {
      cancelEdit()
      return
    }
  }

  if (newValue !== item.value) {
    pendingChanges.value = { ...pendingChanges.value, [item.key]: newValue }
  } else {
    const updated = { ...pendingChanges.value }
    delete updated[item.key]
    pendingChanges.value = updated
  }

  editingKey.value = null
  editValue.value = null
}

const cancelEdit = () => {
  editingKey.value = null
  editValue.value = null
}

const handleResetItem = async (item: HiddenConfigItem) => {
  const updated = { ...pendingChanges.value }
  delete updated[item.key]
  pendingChanges.value = updated

  try {
    await deleteHiddenConfig(item.key)
    notify(`${item.key} 已恢复为默认值`)
    loadData()
  } catch (e: unknown) {
    notify((e as Error).message || '操作失败', 'error')
  }
}

const handleSaveAll = async () => {
  if (!hasChanges.value) return

  saving.value = true
  try {
    const updatedKeys = await updateHiddenConfig(pendingChanges.value)
    pendingChanges.value = {}
    notify(`已保存 ${updatedKeys.length} 项配置`)
    loadData()
  } catch (e: unknown) {
    notify((e as Error).message || '保存失败', 'error')
  } finally {
    saving.value = false
  }
}

const handleDiscardChanges = () => {
  pendingChanges.value = {}
  notify('已放弃修改', 'info')
}

const handleResetAll = () => {
  showConfirm('确认要将所有隐藏参数重置为默认值吗？此操作不可逆。', async () => {
    resetting.value = true
    try {
      await resetHiddenConfig()
      pendingChanges.value = {}
      notify('所有隐藏参数已重置为默认值')
      loadData()
    } catch (e: unknown) {
      notify((e as Error).message || '重置失败', 'error')
    } finally {
      resetting.value = false
    }
  })
}

const showConfirm = (message: string, callback: () => void) => {
  confirmMessage.value = message
  confirmCallback.value = callback
  confirmDialog.value = true
}

const confirmAction = () => {
  confirmDialog.value = false
  if (confirmCallback.value) {
    confirmCallback.value()
    confirmCallback.value = null
  }
}

const notify = (text: string, color: string = 'success') => {
  snackbarText.value = text
  snackbarColor.value = color
  showSnackbar.value = true
}

const loadData = async () => {
  loading.value = true
  try {
    const result = await getHiddenConfig()
    items.value = result.items
    groups.value = result.groups
  } catch (e: unknown) {
    notify((e as Error).message || '加载失败', 'error')
  } finally {
    loading.value = false
  }
}

const handleRefresh = () => {
  loadData()
}

onMounted(() => {
  loadData()
  window.addEventListener('iris:refresh', handleRefresh)
})

onUnmounted(() => {
  window.removeEventListener('iris:refresh', handleRefresh)
})
</script>

<style scoped>
.changed-row {
  background: rgba(255, 152, 0, 0.05);
}

.cursor-pointer {
  cursor: pointer;
}
</style>
