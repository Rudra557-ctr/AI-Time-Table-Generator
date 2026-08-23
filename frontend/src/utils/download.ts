import { getStoredApiKey } from '../api/client'

/** Fetch a file endpoint with the X-API-Key header (if set) and save it via
 * a throwaway object URL — a plain <a href> can't carry a custom header. */
export async function downloadWithAuth(path: string, filename: string): Promise<void> {
  const key = getStoredApiKey()
  const headers = new Headers()
  if (key) headers.set('x-api-key', key)
  const res = await fetch(path, { headers })
  if (!res.ok) throw new Error(`Download failed (${res.status})`)
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
