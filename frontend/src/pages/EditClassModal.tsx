import { useEffect, useMemo, useState } from 'react'
import { Modal } from '../components/common/Modal'
import { Button } from '../components/common/Button'
import { Banner } from '../components/common/Banner'
import { StatusPill } from '../components/common/StatusPill'
import { Icon } from '../components/common/Icon'
import {
  applyEdit,
  checkEdit,
  findAlternativeSlots,
  findRoomAlternatives,
  getDatasetRows,
} from '../api/endpoints'
import { EditRejectedError } from '../api/client'
import type {
  AlternativeSlot,
  EditCheckResponse,
  EditProposal,
  RoomAlternative,
  SoftDelta,
  TimetableRow,
} from '../api/types'
import styles from './EditClassModal.module.css'

const DAY_ORDER = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN']

const SOFT_LABELS: { key: keyof SoftDelta; label: string }[] = [
  { key: 'section_gaps', label: 'Section internal gaps' },
  { key: 'section_isolated', label: 'Section isolated periods' },
  { key: 'faculty_gaps', label: 'Faculty gaps' },
  { key: 'faculty_isolated', label: 'Faculty isolated periods' },
  { key: 'room_wastage', label: 'Room seats wasted' },
]

function SoftDeltaList({ delta }: { delta: SoftDelta }) {
  return (
    <ul className={styles.softList}>
      {SOFT_LABELS.map(({ key, label }) => {
        const d = delta[key]
        if (d.delta === 0) return null
        const worse = d.delta > 0
        return (
          <li key={key} className={worse ? styles.softWorse : styles.softBetter}>
            {label}: {d.before} → {d.after}
          </li>
        )
      })}
      {SOFT_LABELS.every(({ key }) => delta[key].delta === 0) && (
        <li className={styles.softNeutral}>No change to section/faculty compactness or room fit.</li>
      )}
    </ul>
  )
}

function CheckList({ result }: { result: EditCheckResponse }) {
  return (
    <div className={styles.checklist}>
      {result.checks.map((c) => (
        <div key={c.label} className={styles.checkRow}>
          <StatusPill label={c.ok ? 'OK' : 'Fails'} tone={c.ok ? 'ok' : 'error'} />
          <span className={c.ok ? '' : styles.checkFailLabel}>{c.label}</span>
        </div>
      ))}
    </div>
  )
}

interface Props {
  jobId: string
  row: TimetableRow
  courseLabel: string
  onClose: () => void
  onApplied: () => void
}

export function EditClassModal({ jobId, row, courseLabel, onClose, onApplied }: Props) {
  const [timeSlots, setTimeSlots] = useState<Record<string, string>[]>([])
  const [rooms, setRooms] = useState<Record<string, string>[]>([])
  const [faculty, setFaculty] = useState<Record<string, string>[]>([])
  const [loadingOptions, setLoadingOptions] = useState(true)

  const [slotId, setSlotId] = useState(row.slot_id)
  const [roomId, setRoomId] = useState(row.room_id)
  const [facultyId, setFacultyId] = useState(row.faculty_id)

  const [checking, setChecking] = useState(false)
  const [checkResult, setCheckResult] = useState<EditCheckResponse | null>(null)
  const [checkedFor, setCheckedFor] = useState<string | null>(null)
  const [checkError, setCheckError] = useState<string | null>(null)

  const [applying, setApplying] = useState(false)
  const [applyError, setApplyError] = useState<string | null>(null)

  const [showAlternatives, setShowAlternatives] = useState(false)
  const [loadingAlternatives, setLoadingAlternatives] = useState(false)
  const [alternatives, setAlternatives] = useState<AlternativeSlot[] | null>(null)

  const [showRooms, setShowRooms] = useState(false)
  const [loadingRooms, setLoadingRooms] = useState(false)
  const [roomAlternatives, setRoomAlternatives] = useState<RoomAlternative[] | null>(null)

  useEffect(() => {
    setLoadingOptions(true)
    Promise.all([
      getDatasetRows(jobId, 'time_slots'),
      getDatasetRows(jobId, 'rooms'),
      getDatasetRows(jobId, 'faculty'),
    ])
      .then(([ts, rm, fc]) => {
        setTimeSlots(ts.rows)
        setRooms(rm.rows)
        setFaculty(fc.rows)
      })
      .finally(() => setLoadingOptions(false))
  }, [jobId])

  const slotOptions = useMemo(() => {
    return [...timeSlots].sort((a, b) => {
      const da = DAY_ORDER.indexOf(a.day)
      const db = DAY_ORDER.indexOf(b.day)
      if (da !== db) return da - db
      return Number(a.period_number) - Number(b.period_number)
    })
  }, [timeSlots])

  const roomLabel = (r: Record<string, string>) => `${r.room_id} — ${r.room_type}, cap ${r.capacity}`
  const facultyLabel = (f: Record<string, string>) => `${f.faculty_id}${f.name ? ` — ${f.name}` : ''}`

  const proposal: EditProposal = {
    offering_id: row.offering_id,
    session: row.session,
    new_slot_id: slotId,
    new_room_id: roomId,
    new_faculty_id: facultyId,
  }
  const proposalKey = `${slotId}|${roomId}|${facultyId}`
  const hasChange = slotId !== row.slot_id || roomId !== row.room_id || facultyId !== row.faculty_id
  const isStale = checkedFor !== proposalKey

  async function runCheck(p: EditProposal, key: string) {
    setChecking(true)
    setCheckError(null)
    try {
      const result = await checkEdit(jobId, p)
      setCheckResult(result)
      setCheckedFor(key)
    } catch (e) {
      setCheckError(e instanceof Error ? e.message : 'Could not check this change.')
      setCheckResult(null)
    } finally {
      setChecking(false)
    }
  }

  async function loadAlternatives() {
    setShowAlternatives(true)
    setShowRooms(false)
    setLoadingAlternatives(true)
    try {
      const { alternatives } = await findAlternativeSlots(jobId, row.offering_id, row.session)
      setAlternatives(alternatives)
    } finally {
      setLoadingAlternatives(false)
    }
  }

  async function loadRoomAlternatives() {
    setShowRooms(true)
    setShowAlternatives(false)
    setLoadingRooms(true)
    try {
      const { rooms } = await findRoomAlternatives(jobId, row.offering_id, row.session)
      setRoomAlternatives(rooms)
    } finally {
      setLoadingRooms(false)
    }
  }

  function pickAlternative(a: AlternativeSlot) {
    setSlotId(a.slot_id)
    setRoomId(a.room_id)
    setShowAlternatives(false)
    runCheck(
      { offering_id: row.offering_id, session: row.session, new_slot_id: a.slot_id, new_room_id: a.room_id, new_faculty_id: facultyId },
      `${a.slot_id}|${a.room_id}|${facultyId}`,
    )
  }

  function pickRoom(r: RoomAlternative) {
    if (!r.valid) return
    setRoomId(r.room_id)
    setShowRooms(false)
    runCheck(
      { offering_id: row.offering_id, session: row.session, new_slot_id: slotId, new_room_id: r.room_id, new_faculty_id: facultyId },
      `${slotId}|${r.room_id}|${facultyId}`,
    )
  }

  async function submitApply() {
    setApplying(true)
    setApplyError(null)
    try {
      await applyEdit(jobId, proposal)
      onApplied()
      onClose()
    } catch (e) {
      if (e instanceof EditRejectedError) {
        setApplyError(e.violations[0] || e.message)
        // Server is the final authority — refresh the checklist so the UI
        // matches what it just rejected, in case client state was stale.
        runCheck(proposal, proposalKey)
      } else {
        setApplyError(e instanceof Error ? e.message : 'Could not apply this change.')
      }
    } finally {
      setApplying(false)
    }
  }

  const canApply = checkResult?.valid === true && !isStale && !applying

  const footer = (
    <>
      <Button variant="ghost" onClick={onClose}>
        Cancel
      </Button>
      <Button onClick={submitApply} loading={applying} disabled={!canApply}>
        Apply change
      </Button>
    </>
  )

  return (
    <Modal title={`Edit class — ${courseLabel}`} onClose={onClose} wide footer={footer}>
      <div className={styles.currentBlock}>
        <div className={styles.currentRow}>
          <span className={styles.currentLabel}>Section</span>
          <span className="mono">{row.section_id}</span>
        </div>
        <div className={styles.currentRow}>
          <span className={styles.currentLabel}>Current</span>
          <span className="mono">
            {row.day} {row.start_time}–{row.end_time} · {row.room_id} · {row.faculty_id}
          </span>
        </div>
      </div>

      <div className={styles.form}>
        <label className={styles.field}>
          <span>Day &amp; time</span>
          <select value={slotId} onChange={(e) => setSlotId(e.target.value)} disabled={loadingOptions}>
            {slotOptions.map((s) => (
              <option key={s.slot_id} value={s.slot_id}>
                {s.day} {s.start_time}–{s.end_time}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.field}>
          <span>Room</span>
          <select value={roomId} onChange={(e) => setRoomId(e.target.value)} disabled={loadingOptions}>
            {rooms.map((r) => (
              <option key={r.room_id} value={r.room_id}>
                {roomLabel(r)}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.field}>
          <span>Faculty</span>
          <select value={facultyId} onChange={(e) => setFacultyId(e.target.value)} disabled={loadingOptions}>
            {faculty.map((f) => (
              <option key={f.faculty_id} value={f.faculty_id}>
                {facultyLabel(f)}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className={styles.actionsRow}>
        <Button variant="secondary" onClick={() => runCheck(proposal, proposalKey)} loading={checking} disabled={!hasChange}>
          Check
        </Button>
        <Button variant="ghost" onClick={loadRoomAlternatives} disabled={!row.offering_id}>
          <Icon name="room" size={14} /> Compatible rooms
        </Button>
      </div>

      {checkError && (
        <Banner tone="error" title="Couldn't check this change">
          {checkError}
        </Banner>
      )}

      {!hasChange && !checkResult && (
        <p className={styles.hint}>Change the day/time, room, or faculty above, then Check.</p>
      )}

      {checkResult && !isStale && (
        <>
          {checkResult.valid ? (
            <Banner tone="ok" title="Valid — no hard-constraint violations introduced">
              This change is safe to apply.
            </Banner>
          ) : (
            <Banner tone="error" title={`Cannot apply — ${checkResult.new_violations.length} issue(s)`}>
              <ul>
                {checkResult.new_violations.map((v, i) => (
                  <li key={i}>{v}</li>
                ))}
              </ul>
            </Banner>
          )}
          <CheckList result={checkResult} />
          <div className={styles.softBlock}>
            <div className={styles.softTitle}>Soft-quality impact</div>
            <SoftDeltaList delta={checkResult.soft_delta} />
            <div className={styles.weightedDelta}>
              Weighted impact: <span className="mono">{checkResult.weighted_delta > 0 ? '+' : ''}{checkResult.weighted_delta}</span>{' '}
              <span className={styles.weightedNote}>(lower is better; 0 = no measurable change)</span>
            </div>
          </div>
          {checkResult.preexisting_violations.length > 0 && (
            <p className={styles.preexistingNote}>
              Note: this schedule already had {checkResult.preexisting_violations.length} unrelated violation(s) before
              your change — unaffected by it either way.
            </p>
          )}
          {!checkResult.valid && (
            <Button variant="secondary" onClick={loadAlternatives}>
              Find alternative slots
            </Button>
          )}
        </>
      )}

      {showAlternatives && (
        <div className={styles.altPanel}>
          <div className={styles.altTitle}>Alternative slots</div>
          {loadingAlternatives && <p className={styles.hint}>Searching…</p>}
          {!loadingAlternatives && alternatives?.length === 0 && (
            <p className={styles.hint}>No valid alternative found for this session.</p>
          )}
          {!loadingAlternatives &&
            alternatives?.map((a, i) => (
              <button key={i} className={styles.altRow} onClick={() => pickAlternative(a)}>
                <StatusPill label="Valid" tone="ok" />
                <span className="mono">
                  {a.day} {a.start_time} · {a.room_id}
                </span>
                <span className={styles.altImpact}>
                  impact {a.weighted_delta > 0 ? '+' : ''}
                  {a.weighted_delta}
                </span>
              </button>
            ))}
        </div>
      )}

      {showRooms && (
        <div className={styles.altPanel}>
          <div className={styles.altTitle}>Compatible rooms</div>
          {loadingRooms && <p className={styles.hint}>Checking rooms…</p>}
          {!loadingRooms &&
            roomAlternatives?.map((r) => (
              <button
                key={r.room_id}
                className={`${styles.altRow} ${!r.valid ? styles.altRowDisabled : ''}`}
                onClick={() => pickRoom(r)}
                disabled={!r.valid}
              >
                <StatusPill label={r.valid ? 'Valid' : 'Invalid'} tone={r.valid ? 'ok' : 'error'} />
                <span className="mono">
                  {r.room_id} (cap {r.capacity})
                </span>
                {!r.valid && r.reason && <span className={styles.altReason}>{r.reason}</span>}
              </button>
            ))}
        </div>
      )}

      {applyError && (
        <Banner tone="error" title="Could not apply">
          {applyError}
        </Banner>
      )}
    </Modal>
  )
}
