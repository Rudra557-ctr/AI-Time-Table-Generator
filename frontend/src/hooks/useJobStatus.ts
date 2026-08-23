import { useEffect, useRef, useState } from 'react'
import { getStatus } from '../api/endpoints'
import type { StatusResponse } from '../api/types'
import { isTerminalStatus } from '../utils/formatStatus'

interface UseJobStatusOptions {
  intervalMs?: number
  /** Poll only while true — flip off once the caller has its own reason to
   * stop (e.g. hasn't kicked off a solve yet). */
  enabled?: boolean
}

interface UseJobStatusResult {
  status: StatusResponse | null
  error: Error | null
  isPolling: boolean
  refresh: () => void
}

/** Polls GET /api/status/{jobId} on an interval and stops itself once the
 * status is terminal (solved/resolved/error) — the one place both the solve
 * screen and the resolve screen share, since both are "kick off a
 * background job, then watch /api/status until it settles". */
export function useJobStatus(jobId: string | null, opts: UseJobStatusOptions = {}): UseJobStatusResult {
  const { intervalMs = 1500, enabled = true } = opts
  const [status, setStatus] = useState<StatusResponse | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const [isPolling, setIsPolling] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const stoppedRef = useRef(false)

  useEffect(() => {
    stoppedRef.current = false
    if (!jobId || !enabled) return

    setIsPolling(true)

    async function tick() {
      try {
        const s = await getStatus(jobId!)
        if (stoppedRef.current) return
        setStatus(s)
        setError(null)
        if (isTerminalStatus(s.status)) {
          setIsPolling(false)
          return
        }
      } catch (e) {
        if (stoppedRef.current) return
        setError(e instanceof Error ? e : new Error(String(e)))
      }
      if (!stoppedRef.current) {
        timerRef.current = setTimeout(tick, intervalMs)
      }
    }
    tick()

    return () => {
      stoppedRef.current = true
      if (timerRef.current) clearTimeout(timerRef.current)
      setIsPolling(false)
    }
  }, [jobId, enabled, intervalMs])

  const refresh = () => {
    if (jobId) {
      getStatus(jobId)
        .then(setStatus)
        .catch((e) => setError(e instanceof Error ? e : new Error(String(e))))
    }
  }

  return { status, error, isPolling, refresh }
}
