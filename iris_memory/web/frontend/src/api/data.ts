import axios from 'axios'
import apiClient from './request'

interface ApiBaseResponse {
  success: boolean
  error?: string
  message?: string
}

export interface ImportStats {
  total_count: number
  imported_count: number
  skipped_count: number
  error_count: number
}

export interface L3ImportStats {
  imported_nodes: number
  imported_edges: number
  skipped_nodes: number
  error_count: number
}

export interface ProfileImportStats {
  imported_groups: number
  imported_users: number
  skipped: number
  error_count: number
}

const downloadBlob = async (url: string, params: Record<string, string> = {}, defaultFilename: string): Promise<void> => {
  const response = await axios.get(url, {
    params,
    responseType: 'blob',
    withCredentials: true,
  })
  const blob = response.data as Blob
  const contentDisposition = response.headers?.['content-disposition']
  const filenameMatch = contentDisposition?.match(/filename="?(.+?)"?$/)
  const filename = filenameMatch ? filenameMatch[1] : defaultFilename

  const objectUrl = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = objectUrl
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  window.URL.revokeObjectURL(objectUrl)
}

export const exportL2Memory = async (groupId?: string): Promise<void> => {
  const params = groupId ? { group_id: groupId } : {}
  const timestamp = new Date().toISOString().slice(0, 10)
  await downloadBlob('/api/iris/data/l2/export', params, `iris_l2_memory_${timestamp}.json`)
}

export const importL2Memory = async (data: unknown, skipDuplicates: boolean = true): Promise<ImportStats> => {
  const response = await apiClient.post('/data/l2/import', {
    data,
    skip_duplicates: skipDuplicates
  }) as ApiBaseResponse & { stats: ImportStats }
  if (!response.success) {
    throw new Error(response.error || '导入 L2 记忆失败')
  }
  return response.stats
}

export const exportL3KG = async (): Promise<void> => {
  const timestamp = new Date().toISOString().slice(0, 10)
  await downloadBlob('/api/iris/data/l3/export', {}, `iris_l3_kg_${timestamp}.json`)
}

export const importL3KG = async (data: unknown, skipDuplicates: boolean = true): Promise<L3ImportStats> => {
  const response = await apiClient.post('/data/l3/import', {
    data,
    skip_duplicates: skipDuplicates
  }) as ApiBaseResponse & { stats: L3ImportStats }
  if (!response.success) {
    throw new Error(response.error || '导入 L3 知识图谱失败')
  }
  return response.stats
}

export const exportProfiles = async (): Promise<void> => {
  const timestamp = new Date().toISOString().slice(0, 10)
  await downloadBlob('/api/iris/data/profile/export', {}, `iris_profiles_${timestamp}.json`)
}

export const importProfiles = async (data: unknown, skipDuplicates: boolean = true): Promise<ProfileImportStats> => {
  const response = await apiClient.post('/data/profile/import', {
    data,
    skip_duplicates: skipDuplicates
  }) as ApiBaseResponse & { stats: ProfileImportStats }
  if (!response.success) {
    throw new Error(response.error || '导入画像失败')
  }
  return response.stats
}

export const exportAll = async (): Promise<void> => {
  const timestamp = new Date().toISOString().slice(0, 10)
  await downloadBlob('/api/iris/data/all/export', {}, `iris_full_backup_${timestamp}.json`)
}

export const importAll = async (data: unknown, skipDuplicates: boolean = true): Promise<Record<string, unknown>> => {
  const response = await apiClient.post('/data/all/import', {
    data,
    skip_duplicates: skipDuplicates
  }) as ApiBaseResponse & { result: Record<string, unknown> }
  if (!response.success) {
    throw new Error(response.error || '全量导入失败')
  }
  return response.result
}
