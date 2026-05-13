const bridge = window.AstrBotPluginPage as any

let readyPromise: Promise<any> | null = null

function ensureReady(): Promise<any> {
  if (!readyPromise) {
    readyPromise = bridge.ready()
  }
  return readyPromise
}

async function apiGet<T = any>(endpoint: string, params?: Record<string, any>): Promise<T> {
  await ensureReady()
  return bridge.apiGet(endpoint, params)
}

async function apiPost<T = any>(endpoint: string, body?: any): Promise<T> {
  await ensureReady()
  return bridge.apiPost(endpoint, body)
}

async function apiDownload(endpoint: string, params?: Record<string, string>, filename?: string): Promise<void> {
  await ensureReady()
  return bridge.download(endpoint, params, filename)
}

async function apiUpload<T = any>(endpoint: string, file: File): Promise<T> {
  await ensureReady()
  return bridge.upload(endpoint, file)
}

export { apiGet, apiPost, apiDownload, apiUpload, ensureReady }
