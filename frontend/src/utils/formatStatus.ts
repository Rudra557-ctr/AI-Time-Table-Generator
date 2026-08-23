export type StatusTone = 'ok' | 'warn' | 'error' | 'neutral' | 'pending'

export interface StatusDisplay {
  label: string
  tone: StatusTone
}

const TERMINAL_STATUSES = new Set([
  'OPTIMAL_SOFT',
  'FEASIBLE_SOFT',
  'HARD_ONLY_FALLBACK',
  'INFEASIBLE',
  'UNKNOWN',
  'RESOLVED',
  'OPTIMIZED',
  'OPTIMIZE_FAILED',
])

export function isErrorStatus(status: string | undefined): boolean {
  return !!status && status.startsWith('ERROR:')
}

export function isPendingStatus(status: string | undefined): boolean {
  return status === 'solving' || status === 'resolving' || status === 'uploaded' || status === 'optimizing'
}

export function isTerminalStatus(status: string | undefined): boolean {
  if (!status) return false
  return isErrorStatus(status) || TERMINAL_STATUSES.has(status)
}

/** The one place that turns a raw backend status string into display copy.
 * Deliberately never says "optimal" unless the backend literally reported
 * OPTIMAL_SOFT — FEASIBLE_SOFT and HARD_ONLY_FALLBACK are valid, useful
 * results, but not proven-optimal ones, and must not be blurred together. */
export function formatStatus(status: string | undefined): StatusDisplay {
  if (!status) return { label: 'Idle', tone: 'neutral' }
  if (isErrorStatus(status)) return { label: status.replace(/^ERROR:\s*/, 'Error — '), tone: 'error' }
  switch (status) {
    case 'uploaded':
      return { label: 'Data uploaded', tone: 'neutral' }
    case 'solving':
      return { label: 'Solving…', tone: 'pending' }
    case 'resolving':
      return { label: 'Re-solving…', tone: 'pending' }
    case 'optimizing':
      return { label: 'Optimizing…', tone: 'pending' }
    case 'OPTIMAL_SOFT':
      return { label: 'Optimal (proven)', tone: 'ok' }
    case 'FEASIBLE_SOFT':
      return { label: 'Feasible — not proven optimal', tone: 'ok' }
    case 'HARD_ONLY_FALLBACK':
      return { label: 'Valid, unoptimized fallback', tone: 'warn' }
    case 'INFEASIBLE':
      return { label: 'Infeasible — no valid schedule exists', tone: 'error' }
    case 'UNKNOWN':
      return { label: 'No solution found in time budget', tone: 'warn' }
    case 'RESOLVED':
      return { label: 'Re-solved', tone: 'ok' }
    case 'OPTIMIZED':
      return { label: 'Optimized', tone: 'ok' }
    case 'OPTIMIZE_FAILED':
      return { label: "Didn't converge — kept the existing schedule", tone: 'warn' }
    default:
      // Unknown future status from the backend — show it verbatim rather
      // than hiding it or crashing.
      return { label: status, tone: 'neutral' }
  }
}
