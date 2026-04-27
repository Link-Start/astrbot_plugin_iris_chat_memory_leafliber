import apiClient from './request'

interface ApiBaseResponse {
  success: boolean
  error?: string
  message?: string
}

export const clearL1Buffer = async (groupId?: string): Promise<{ cleared_count: number }> => {
  const response = await apiClient.post('/manage/l1/clear', {
    group_id: groupId || undefined
  }) as unknown as ApiBaseResponse & { cleared_count: number }
  if (!response.success) {
    throw new Error(response.error || '清空 L1 缓冲失败')
  }
  return { cleared_count: response.cleared_count }
}

export const deleteL2Memory = async (scope: 'all' | 'group', groupId?: string): Promise<{ deleted_count: number }> => {
  const response = await apiClient.post('/manage/l2/delete', {
    scope,
    group_id: groupId
  }) as unknown as ApiBaseResponse & { deleted_count: number }
  if (!response.success) {
    throw new Error(response.error || '删除 L2 记忆失败')
  }
  return { deleted_count: response.deleted_count }
}

export const deleteL3KG = async (scope: 'all' | 'group', groupId?: string): Promise<{ deleted_count: number }> => {
  const response = await apiClient.post('/manage/l3/delete', {
    scope,
    group_id: groupId
  }) as unknown as ApiBaseResponse & { deleted_count: number }
  if (!response.success) {
    throw new Error(response.error || '删除 L3 图谱失败')
  }
  return { deleted_count: response.deleted_count }
}

export const mergeL3Duplicates = async (): Promise<{ merged_count: number; deleted_count: number }> => {
  const response = await apiClient.post('/manage/l3/merge-duplicates') as unknown as ApiBaseResponse & { merged_count: number; deleted_count: number }
  if (!response.success) {
    throw new Error(response.error || '合并重复节点失败')
  }
  return { merged_count: response.merged_count, deleted_count: response.deleted_count }
}

export const deleteProfile = async (
  scope: 'group' | 'user' | 'all',
  groupId?: string,
  userId?: string
): Promise<Record<string, unknown>> => {
  const response = await apiClient.post('/manage/profile/delete', {
    scope,
    group_id: groupId,
    user_id: userId
  }) as unknown as ApiBaseResponse & Record<string, unknown>
  if (!response.success) {
    throw new Error(response.error || '删除画像失败')
  }
  return response
}

export type TaskName = 'forgetting' | 'merge' | 'kg_extraction' | 'cache_cleanup'

export const triggerTask = async (task: TaskName): Promise<{ message: string }> => {
  const response = await apiClient.post('/manage/tasks/trigger', {
    task
  }) as unknown as ApiBaseResponse & { message: string }
  if (!response.success) {
    throw new Error(response.error || '触发任务失败')
  }
  return { message: response.message }
}

export interface TaskStatus {
  running: boolean
}

export const getTasksStatus = async (): Promise<Record<string, TaskStatus>> => {
  const response = await apiClient.get('/manage/tasks/status') as unknown as ApiBaseResponse & { tasks: Record<string, TaskStatus> }
  if (!response.success) {
    throw new Error(response.error || '获取任务状态失败')
  }
  return response.tasks
}
