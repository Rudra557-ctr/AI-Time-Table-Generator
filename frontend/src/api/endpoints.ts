import { apiFetch } from './client'
import type {
  DatasetRowsResponse,
  OptimizeKickoff,
  PrecheckResponse,
  ReportResponse,
  ResolveKickoff,
  SolveKickoff,
  StatusResponse,
  UploadResponse,
} from './types'

function filesFormData(files: File[]): FormData {
  const fd = new FormData()
  for (const f of files) fd.append('files', f)
  return fd
}

export function uploadFiles(files: File[], opts?: { fill?: boolean }): Promise<UploadResponse> {
  const qs = opts?.fill ? '?fill=true' : ''
  return apiFetch<UploadResponse>(`/api/upload${qs}`, { method: 'POST', body: filesFormData(files) })
}

export function solveJob(
  jobId: string,
  opts?: { hardTimeLimit?: number; softTimeLimit?: number; weights?: Record<string, number> },
): Promise<SolveKickoff> {
  const params = new URLSearchParams()
  if (opts?.hardTimeLimit) params.set('hard_time_limit', String(opts.hardTimeLimit))
  if (opts?.softTimeLimit) params.set('soft_time_limit', String(opts.softTimeLimit))
  const qs = params.toString() ? `?${params.toString()}` : ''
  return apiFetch<SolveKickoff>(`/api/solve/${jobId}${qs}`, {
    method: 'POST',
    body: JSON.stringify(opts?.weights ?? null),
  })
}

export function resolveJob(
  jobId: string,
  files: File[],
  opts?: { stabilityTimeLimit?: number; tier1TimeLimit?: number; tier2TimeLimit?: number; tier3TimeLimit?: number },
): Promise<ResolveKickoff> {
  const params = new URLSearchParams()
  if (opts?.stabilityTimeLimit) params.set('stability_time_limit', String(opts.stabilityTimeLimit))
  if (opts?.tier1TimeLimit) params.set('tier1_time_limit', String(opts.tier1TimeLimit))
  if (opts?.tier2TimeLimit) params.set('tier2_time_limit', String(opts.tier2TimeLimit))
  if (opts?.tier3TimeLimit) params.set('tier3_time_limit', String(opts.tier3TimeLimit))
  const qs = params.toString() ? `?${params.toString()}` : ''
  return apiFetch<ResolveKickoff>(`/api/resolve/${jobId}${qs}`, { method: 'POST', body: filesFormData(files) })
}

export function optimizeJob(
  jobId: string,
  opts?: { lnsMaxRounds?: number; tier2TimeLimit?: number; tier3TimeLimit?: number; polish?: boolean },
): Promise<OptimizeKickoff> {
  const params = new URLSearchParams()
  if (opts?.lnsMaxRounds) params.set('lns_max_rounds', String(opts.lnsMaxRounds))
  if (opts?.tier2TimeLimit) params.set('tier2_time_limit', String(opts.tier2TimeLimit))
  if (opts?.tier3TimeLimit) params.set('tier3_time_limit', String(opts.tier3TimeLimit))
  if (opts?.polish) params.set('polish', 'true')
  const qs = params.toString() ? `?${params.toString()}` : ''
  return apiFetch<OptimizeKickoff>(`/api/optimize/${jobId}${qs}`, { method: 'POST' })
}

export function getStatus(jobId: string): Promise<StatusResponse> {
  return apiFetch<StatusResponse>(`/api/status/${jobId}`)
}

// Plain paths, not full download triggers — the X-API-Key header (when set)
// can't ride along on a bare <a href> navigation, so actual downloads go
// through utils/download.ts's downloadWithAuth() instead, which fetches
// with the header and saves the resulting blob.
export function getDownloadPath(jobId: string): string {
  return `/api/download/${jobId}`
}

export function getDownloadClassPath(jobId: string, section: string): string {
  return `/api/download_class/${jobId}/${encodeURIComponent(section)}`
}

export function getWeightDefaults(): Promise<Record<string, number>> {
  return apiFetch<Record<string, number>>('/api/weights/defaults')
}

export function getDatasetRows(jobId: string, dataset: string): Promise<DatasetRowsResponse> {
  return apiFetch<DatasetRowsResponse>(`/api/data/${jobId}/${dataset}`)
}

export function getReport(jobId: string): Promise<ReportResponse> {
  return apiFetch<ReportResponse>(`/api/report/${jobId}`)
}

export function getPrecheck(jobId: string): Promise<PrecheckResponse> {
  return apiFetch<PrecheckResponse>(`/api/precheck/${jobId}`)
}

export async function fetchTimetableCsvText(jobId: string): Promise<string> {
  const res = await fetch(`/api/download/${jobId}`)
  if (!res.ok) throw new Error(`Could not load timetable (${res.status})`)
  return res.text()
}
