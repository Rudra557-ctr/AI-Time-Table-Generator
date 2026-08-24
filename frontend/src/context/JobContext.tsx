import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import type { UploadResponse } from '../api/types'

const JOB_ID_KEY = 'sih-timetable-job-id'
const UPLOAD_RESULT_KEY = 'sih-timetable-upload-result'

interface JobContextValue {
  jobId: string | null
  uploadResult: UploadResponse | null
  hasSolved: boolean
  setJob: (jobId: string, uploadResult: UploadResponse) => void
  switchJob: (jobId: string, solved: boolean) => void
  markSolved: () => void
  clearJob: () => void
}

const JobContext = createContext<JobContextValue | null>(null)

function readStored<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : null
  } catch {
    return null
  }
}

function writeStored(key: string, value: unknown): void {
  try {
    if (value === null || value === undefined) localStorage.removeItem(key)
    else localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // ignore
  }
}

/** The app tracks a single "current job" — matching the reference UI, which
 * has no per-job URLs, just one working session at a time. Persisted to
 * localStorage so a page refresh doesn't lose the in-progress dataset. */
export function JobProvider({ children }: { children: ReactNode }) {
  const [jobId, setJobId] = useState<string | null>(() => readStored<string>(JOB_ID_KEY))
  const [uploadResult, setUploadResult] = useState<UploadResponse | null>(() =>
    readStored<UploadResponse>(UPLOAD_RESULT_KEY),
  )
  const [hasSolved, setHasSolved] = useState(false)

  useEffect(() => writeStored(JOB_ID_KEY, jobId), [jobId])
  useEffect(() => writeStored(UPLOAD_RESULT_KEY, uploadResult), [uploadResult])

  const setJob = (id: string, result: UploadResponse) => {
    setJobId(id)
    setUploadResult(result)
    setHasSolved(false)
  }

  const markSolved = () => setHasSolved(true)

  // Reopens a job that was generated in a past session (from the History
  // page) rather than one just produced by this session's own upload+solve
  // flow — so there's no fresh UploadResponse to hand over. Downstream pages
  // fall back to the fetched StatusResponse's own audit/report for the
  // dataset summary once uploadResult is null (see DashboardPage).
  const switchJob = (id: string, solved: boolean) => {
    setJobId(id)
    setUploadResult(null)
    setHasSolved(solved)
  }

  const clearJob = () => {
    setJobId(null)
    setUploadResult(null)
    setHasSolved(false)
  }

  return (
    <JobContext.Provider value={{ jobId, uploadResult, hasSolved, setJob, switchJob, markSolved, clearJob }}>
      {children}
    </JobContext.Provider>
  )
}

export function useJob(): JobContextValue {
  const ctx = useContext(JobContext)
  if (!ctx) throw new Error('useJob must be used within a JobProvider')
  return ctx
}
