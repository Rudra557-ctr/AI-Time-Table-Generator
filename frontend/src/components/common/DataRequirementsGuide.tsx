import { Card } from './Card'
import { Banner } from './Banner'
import { StatusPill } from './StatusPill'
import styles from './DataRequirementsGuide.module.css'

interface GuideFile {
  key: string
  file: string
  impact: string
}

interface GuideTier {
  title: string
  description: string
  missingTone: 'error' | 'warn' | 'neutral'
  files: GuideFile[]
}

/** What each recognized dataset actually does in sih_solver, verified against
 * the real code (not guessed) so this guide never tells a user something
 * that isn't true: required = quick_solvability_check's 7-file blocker list
 * (sih_solver/dataset.py); accuracy = faculty_availability.csv/
 * room_availability.csv, consumed by add_availability_constraints
 * (full_model.py) -- gracefully skipped when wholly absent, but a faculty/
 * room member left OUT of an otherwise-populated file becomes unschedulable
 * at every slot, not "always available"; electives = students+
 * student_enrollments (add_student_collision, hard.py) and elective_groups+
 * elective_group_courses (add_synchronized_constraints, hard.py) -- both
 * pairs degrade gracefully (constraint just isn't added) when absent;
 * situational = fixed_events.csv (add_fixed_events, full_model.py);
 * info-only = programs/departments/universities/academic_rules, confirmed
 * unread by any solver code today. */
const GUIDE: GuideTier[] = [
  {
    title: 'Required',
    description: "Without ALL seven of these, the solver can't run at all.",
    missingTone: 'error',
    files: [
      { key: 'courses', file: 'courses.csv', impact: 'The course catalog.' },
      { key: 'rooms', file: 'rooms.csv', impact: 'Room inventory.' },
      { key: 'faculty', file: 'faculty.csv', impact: 'Faculty roster.' },
      { key: 'faculty_courses', file: 'faculty_courses.csv', impact: 'Which faculty can teach which course.' },
      { key: 'course_offerings', file: 'course_offerings.csv', impact: 'Which course is offered to which section — the actual list of classes needing a slot.' },
      { key: 'sections', file: 'sections.csv', impact: 'The class/section groups being scheduled.' },
      { key: 'time_slots', file: 'time_slots.csv', impact: 'The schedulable time grid itself.' },
    ],
  },
  {
    title: 'Strongly recommended — accuracy',
    description: 'Optional, but skipping means the solver assumes everyone and everywhere is always available.',
    missingTone: 'warn',
    files: [
      { key: 'faculty_availability', file: 'faculty_availability.csv', impact: 'Real faculty availability (e.g. guest/visiting faculty on fixed days). Missing entirely → everyone assumed available at every slot.' },
      { key: 'room_availability', file: 'room_availability.csv', impact: 'Real room availability (maintenance, reservations). Missing entirely → every room assumed always available.' },
    ],
  },
  {
    title: 'Recommended — NEP2020 electives',
    description: 'These four work together — enables per-student elective clash protection and cross-section sync.',
    missingTone: 'warn',
    files: [
      { key: 'students', file: 'students.csv', impact: 'Individual student roster.' },
      { key: 'student_enrollments', file: 'student_enrollments.csv', impact: 'Which electives each student picked — enables per-student clash checking.' },
      { key: 'elective_groups', file: 'elective_groups.csv', impact: 'Defines PCE/OAE elective groups.' },
      { key: 'elective_group_courses', file: 'elective_group_courses.csv', impact: 'Links electives to their group — enables cross-section synchronization.' },
    ],
  },
  {
    title: 'Situational',
    description: 'Only matters if it applies to your institution.',
    missingTone: 'neutral',
    files: [
      { key: 'fixed_events', file: 'fixed_events.csv', impact: 'Blocks fixed institutional events (assembly, holidays) from being scheduled over.' },
    ],
  },
  {
    title: 'Informational only',
    description: "Doesn't change the generated schedule — used for display/labeling elsewhere in the app.",
    missingTone: 'neutral',
    files: [
      { key: 'programs', file: 'programs.csv', impact: 'Programme names (shown on the Electives page).' },
      { key: 'departments', file: 'departments.csv', impact: 'Department names.' },
      { key: 'universities', file: 'universities.csv', impact: 'Campus/academic year metadata.' },
      { key: 'academic_rules', file: 'academic_rules.csv', impact: 'Not yet used by the solver.' },
    ],
  },
]

export function DataRequirementsGuide({ audit }: { audit?: Record<string, number> }) {
  return (
    <div className={styles.wrap}>
      {GUIDE.map((tier) => (
        <div key={tier.title} className={styles.tier}>
          <h4 className={styles.tierTitle}>{tier.title}</h4>
          <p className={styles.tierDesc}>{tier.description}</p>
          <ul className={styles.fileList}>
            {tier.files.map((f) => {
              const count = audit?.[f.key]
              const known = audit !== undefined && count !== undefined
              return (
                <li key={f.key} className={styles.fileRow}>
                  <div className={styles.fileHead}>
                    <span className="mono">{f.file}</span>
                    {known && (
                      <StatusPill
                        label={count > 0 ? `${count} rows` : 'Missing'}
                        tone={count > 0 ? 'ok' : tier.missingTone}
                      />
                    )}
                  </div>
                  <p className={styles.fileImpact}>{f.impact}</p>
                </li>
              )
            })}
          </ul>
        </div>
      ))}
      <Card>
        <Banner tone="warn" title="If you provide faculty_availability.csv or room_availability.csv, list EVERYONE">
          Leaving a faculty member or room out of an otherwise-populated availability file makes them unschedulable
          at every slot — the opposite of "always available." Either list every faculty member/room, or skip the
          file entirely.
        </Banner>
      </Card>
    </div>
  )
}
