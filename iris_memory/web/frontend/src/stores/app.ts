import { defineStore } from 'pinia'
import { ref } from 'vue'

const THEME_STORAGE_KEY = 'iris_memory_theme'

function loadThemePreference(): boolean {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY)
    if (stored === 'light') return false
    if (stored === 'dark') return true
  } catch {
    // localStorage 不可用时忽略，使用默认值
  }
  return true
}

function saveThemePreference(isDark: boolean): void {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, isDark ? 'dark' : 'light')
  } catch {
    // 忽略写入失败
  }
}

export const useAppStore = defineStore('app', () => {
  // 加载状态
  const loading = ref(false)
  const error = ref<string | null>(null)

  // 选中的群聊
  const selectedGroupId = ref<string | null>(null)

  // 主题（从 localStorage 恢复，默认夜间模式）
  const darkMode = ref(loadThemePreference())

  // 设置加载状态
  const setLoading = (value: boolean) => {
    loading.value = value
  }

  // 设置错误
  const setError = (msg: string | null) => {
    error.value = msg
  }

  // 清除错误
  const clearError = () => {
    error.value = null
  }

  // 选中群聊
  const selectGroup = (groupId: string | null) => {
    selectedGroupId.value = groupId
  }

  // 切换主题
  const toggleTheme = () => {
    darkMode.value = !darkMode.value
    saveThemePreference(darkMode.value)
  }

  return {
    loading,
    error,
    selectedGroupId,
    darkMode,
    setLoading,
    setError,
    clearError,
    selectGroup,
    toggleTheme
  }
})
