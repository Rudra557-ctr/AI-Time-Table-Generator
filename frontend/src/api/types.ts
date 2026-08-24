// Shapes mirror backend/app.py exactly (verified against the running source,
// not guessed). `status` and similar fields are kept as `string`, not a
// union, on purpose: the backend can add a new status/warning shape without
// this file needing an edit — see normalize.ts / formatStatus.ts for the one
// place that interprets these strings.

export interface UploadReportEntry {
  [key: string]: unknown
}

export interface UploadResponse {
  job_id: string
  report: UploadReportEntry
  audit: Record<string, number>
  next?: string
}

export interface ApiErrorBody {
  error: string
  blockers?: string[]
  warnings?: string[]
}

export interface SolveKickoff {
  job_id: string
  status: 'solving'
  poll: string
  warnings?: string[]
}

export interface ResolveKickoff {
  job_id: string
  status: 'resolving'
  poll: string
  warnings?: string[]
}

export interface OptimizeKickoff {
  job_id: string
  status: 'optimizing'
  poll: string
}

// solve_pipeline.py's changed[] entries: for "Teacher" (assigned once per
// offering), key is the bare offering_id string. For "Start"/"Room" (once
// per session), key is the Python tuple (offering_id, session_index),
// which JSON-serializes as a 2-element array — confirmed against a real
// /api/resolve response, not assumed from the docstring alone.
export interface ChangedEntry {
  kind: string
  key: string | [string, number]
  old: string
  new: string
}

export interface StatusResponse {
  job_id: string
  status: string
  dir?: string
  report?: UploadReportEntry
  audit?: Record<string, number>

  // solve fields
  hard_status?: string
  soft_status?: string
  seed_used?: number
  hard_seconds?: number
  soft_seconds?: number
  objective?: number | null
  weights_used?: Record<string, number>
  warnings?: string[]
  output?: string | null

  // resolve fields
  tier_results?: unknown
  final_tier_reached?: string
  total_seconds?: number
  changed_count?: number
  changed?: ChangedEntry[]

  // optimize (LNS gap-repair) fields
  lns_rounds?: unknown[]
  lns_objective?: number
  lns_starting_objective?: number
  lns_seconds?: number

  // error fields
  trace?: string
}

export interface PrecheckResponse {
  blockers: string[]
  warnings: string[]
}

export interface DatasetRowsResponse {
  dataset: string
  count: number
  rows: Record<string, string>[]
}

export interface GapSegmentSummary {
  entity_days: number
  entities: number
  total_gaps: number
  mean_gaps_per_day: number
  zero_gap_days: number
  one_gap_days: number
  multi_gap_days: number
  multi_gap_day_pct: number
  total_isolated_runs: number
  mean_span: number
  max_consecutive_run_observed: number
  run_length_histogram: Record<string, number>
  mean_working_days: number
}

export interface ReportResponse {
  sections: GapSegmentSummary
  faculty: GapSegmentSummary
}

export interface TimetableRow {
  offering_id: string
  course_id: string
  section_id: string
  session: string
  slot_id: string
  day: string
  start_time: string
  end_time: string
  room_id: string
  faculty_id: string
}
