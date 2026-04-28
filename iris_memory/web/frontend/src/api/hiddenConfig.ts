import apiClient from './request'

export interface HiddenConfigItem {
  key: string
  value: unknown
  default: unknown
  type: 'int' | 'float' | 'bool' | 'string' | 'literal'
  description: string
  group: string
  options: string[]
}

export interface HiddenConfigGroup {
  name: string
  keys: string[]
}

interface HiddenConfigResponse {
  success: boolean
  error?: string
  items: HiddenConfigItem[]
  groups: HiddenConfigGroup[]
}

interface UpdateResponse {
  success: boolean
  error?: string
  updated_keys?: string[]
}

interface DeleteResponse {
  success: boolean
  error?: string
  message?: string
}

export const getHiddenConfig = async (): Promise<{ items: HiddenConfigItem[]; groups: HiddenConfigGroup[] }> => {
  const response = await apiClient.get('/hidden-config/') as unknown as HiddenConfigResponse
  if (!response.success) {
    throw new Error(response.error || '获取隐藏配置失败')
  }
  return { items: response.items, groups: response.groups }
}

export const updateHiddenConfig = async (updates: Record<string, unknown>): Promise<string[]> => {
  const response = await apiClient.put('/hidden-config/', { updates }) as unknown as UpdateResponse
  if (!response.success) {
    throw new Error(response.error || '更新隐藏配置失败')
  }
  return response.updated_keys || []
}

export const deleteHiddenConfig = async (key: string): Promise<string> => {
  const response = await apiClient.delete(`/hidden-config/${key}`) as unknown as DeleteResponse
  if (!response.success) {
    throw new Error(response.error || '删除配置项失败')
  }
  return response.message || ''
}

export const resetHiddenConfig = async (): Promise<string> => {
  const response = await apiClient.post('/hidden-config/reset') as unknown as DeleteResponse
  if (!response.success) {
    throw new Error(response.error || '重置隐藏配置失败')
  }
  return response.message || ''
}
