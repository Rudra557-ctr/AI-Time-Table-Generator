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

  // manual-edit workflow fields (set by /api/edit/*)
  publish_state?: 'draft' | 'published'
  last_validated_clean?: boolean

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

// --- Admin manual timetable editing (sih_solver/manual_edit.py) ---------

export interface EditProposal {
  offering_id: string
  session: string
  new_slot_id?: string
  new_room_id?: string
  new_faculty_id?: string
}

export interface EditCheckItem {
  label: string
  ok: boolean
}

export interface SoftDeltaItem {
  before: number
  after: number
  delta: number
}

export interface SoftDelta {
  section_gaps: SoftDeltaItem
  section_isolated: SoftDeltaItem
  faculty_gaps: SoftDeltaItem
  faculty_isolated: SoftDeltaItem
  room_wastage: SoftDeltaItem
}

export interface EditCheckResponse {
  valid: boolean
  checks: EditCheckItem[]
  new_violations: string[]
  preexisting_violations: string[]
  warnings: string[]
  soft_delta: SoftDelta
  weighted_delta: number
}

export interface EditSnapshot {
  slot_id: string
  room_id: string
  faculty_id: string
  day: string
  start_time: string
  end_time: string
}

export interface EditHistoryEntry {
  id: string
  timestamp: number
  kind: string
  offering_id: string
  session: string
  before: EditSnapshot | null
  after: EditSnapshot | null
  soft_delta: SoftDelta
  weighted_delta: number
  undoes?: string
  undone?: boolean
}

export interface EditApplyResponse {
  valid: boolean
  checks: EditCheckItem[]
  soft_delta: SoftDelta
  weighted_delta: number
  entry: EditHistoryEntry
}

export interface AlternativeSlot {
  slot_id: string
  day: string
  start_time: string
  room_id: string
  valid: boolean
  soft_delta: SoftDelta
  weighted_delta: number
}

export interface RoomAlternative {
  room_id: string
  capacity: number
  valid: boolean
  reason: string | null
}

export interface ValidateAllResponse {
  violations: string[]
  warnings: string[]
  sessions_checked: number
  clean: boolean
  soft_quality: ReportResponse | null
}

export type PublishState = 'draft' | 'published'

// --- Recent timetables (job history across all uploads) ------------------

export interface JobSummary {
  job_id: string
  created_at: number
  sequence: number | null
  name: string | null
  status: string | null
  publish_state: PublishState | null
  has_timetable: boolean
  sections: number | null
  faculty: number | null
  rooms: number | null
  courses: number | null
}

export interface JobListResponse {
  jobs: JobSummary[]
}
