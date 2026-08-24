import { apiFetch } from './client'
import type {
  AlternativeSlot,
  DatasetRowsResponse,
  EditApplyResponse,
  EditCheckResponse,
  EditHistoryEntry,
  EditProposal,
  JobListResponse,
  OptimizeKickoff,
  PrecheckResponse,
  ReportResponse,
  ResolveKickoff,
  RoomAlternative,
  SolveKickoff,
  StatusResponse,
  UploadResponse,
  ValidateAllResponse,
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

export function listJobs(limit = 5): Promise<JobListResponse> {
  return apiFetch<JobListResponse>(`/api/jobs?limit=${limit}`)
}

export function deleteJob(jobId: string): Promise<{ job_id: string; deleted: boolean }> {
  return apiFetch<{ job_id: string; deleted: boolean }>(`/api/jobs/${jobId}`, { method: 'DELETE' })
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

// --- Admin manual timetable editing (sih_solver/manual_edit.py) ---------
// All synchronous — every op is a single-row CSV mutation plus a bounded
// validate() call, not a solve, so none of these need the kickoff+poll
// shape solveJob/resolveJob/optimizeJob use.

export function checkEdit(jobId: string, edit: EditProposal): Promise<EditCheckResponse> {
  return apiFetch<EditCheckResponse>(`/api/edit/${jobId}/check`, {
    method: 'POST',
    body: JSON.stringify(edit),
  })
}

export function applyEdit(jobId: string, edit: EditProposal): Promise<EditApplyResponse> {
  return apiFetch<EditApplyResponse>(`/api/edit/${jobId}/apply`, {
    method: 'POST',
    body: JSON.stringify(edit),
  })
}

export function findAlternativeSlots(
  jobId: string,
  offeringId: string,
  session: string,
  maxResults = 5,
): Promise<{ alternatives: AlternativeSlot[] }> {
  return apiFetch<{ alternatives: AlternativeSlot[] }>(`/api/edit/${jobId}/alternatives`, {
    method: 'POST',
    body: JSON.stringify({ offering_id: offeringId, session, max_results: maxResults }),
  })
}

export function findRoomAlternatives(
  jobId: string,
  offeringId: string,
  session: string,
): Promise<{ rooms: RoomAlternative[] }> {
  return apiFetch<{ rooms: RoomAlternative[] }>(`/api/edit/${jobId}/room-alternatives`, {
    method: 'POST',
    body: JSON.stringify({ offering_id: offeringId, session }),
  })
}

export function getEditHistory(jobId: string): Promise<{ history: EditHistoryEntry[] }> {
  return apiFetch<{ history: EditHistoryEntry[] }>(`/api/edit/${jobId}/history`)
}

export function undoLastEdit(jobId: string): Promise<EditApplyResponse> {
  return apiFetch<EditApplyResponse>(`/api/edit/${jobId}/undo`, { method: 'POST' })
}

export function validateAllEdits(jobId: string): Promise<ValidateAllResponse> {
  return apiFetch<ValidateAllResponse>(`/api/edit/${jobId}/validate`, { method: 'POST' })
}

export function publishTimetable(jobId: string): Promise<{ publish_state: 'published' }> {
  return apiFetch<{ publish_state: 'published' }>(`/api/edit/${jobId}/publish`, { method: 'POST' })
}
