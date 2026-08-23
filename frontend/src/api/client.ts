import type { ApiErrorBody } from './types'

const API_KEY_STORAGE_KEY = 'sih-timetable-api-key'

export function getStoredApiKey(): string {
  try {
    return localStorage.getItem(API_KEY_STORAGE_KEY) || ''
  } catch {
    return ''
  }
}

export function setStoredApiKey(key: string): void {
  try {
    if (key) localStorage.setItem(API_KEY_STORAGE_KEY, key)
    else localStorage.removeItem(API_KEY_STORAGE_KEY)
  } catch {
    // ignore — private browsing / storage disabled
  }
}

export class ApiError extends Error {
  status: number
  body: unknown
  constructor(message: string, status: number, body: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }
}

/** Thrown on HTTP 422 from /api/solve or /api/resolve — a structural
 * blocker found by quick_solvability_check, distinct from a generic
 * request/network failure so callers can render BlockersPanel instead of
 * a plain error banner. */
export class SolveBlockedError extends ApiError {
  blockers: string[]
  warnings: string[]
  constructor(body: ApiErrorBody) {
    super(body.error, 422, body)
    this.name = 'SolveBlockedError'
    this.blockers = body.blockers || []
    this.warnings = body.warnings || []
  }
}

/** Thrown on HTTP 400 from /api/resolve — no prior /api/solve for this job. */
export class ResolveRequiresSolveError extends ApiError {
  constructor(body: ApiErrorBody) {
    super(body.error, 400, body)
    this.name = 'ResolveRequiresSolveError'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const key = getStoredApiKey()
  const headers = new Headers(init?.headers)
  if (key) headers.set('x-api-key', key)
  if (init?.body && typeof init.body === 'string' && !headers.has('content-type')) {
    headers.set('content-type', 'application/json')
  }

  const res = await fetch(path, { ...init, headers })

  if (!res.ok) {
    let body: ApiErrorBody = { error: `Request failed (${res.status})` }
    try {
      body = await res.json()
    } catch {
      // non-JSON error body — keep the generic message
    }
    if (res.status === 422 && path.includes('/api/solve')) throw new SolveBlockedError(body)
    if (res.status === 422 && path.includes('/api/resolve')) throw new SolveBlockedError(body)
    if (res.status === 400 && path.includes('/api/resolve')) throw new ResolveRequiresSolveError(body)
    throw new ApiError(body.error || res.statusText, res.status, body)
  }

  return (await res.json()) as T
}

export function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  return request<T>(path, init)
}
