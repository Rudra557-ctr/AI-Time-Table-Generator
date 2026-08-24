/** Maps a quick_solvability_check blocker/warning string (sih_solver/dataset.py:96-200)
 * to a one-line actionable fix. There are exactly 8 fixed message templates there
 * today, each with a distinctive lead-in phrase this matches against. Returns null
 * on no match rather than a generic filler — if backend wording ever drifts, silently
 * showing no suggestion is safer than showing a wrong one. */
export function suggestFix(message: string): string | null {
  let m: RegExpMatchArray | null

  m = message.match(/^Required file '([^']+)' is missing or empty/)
  if (m) return `Upload a valid ${m[1]} on the Upload Data page — the solver can't run without it.`

  m = message.match(/have a blank '([^']+)'/) || message.match(/have the identical '([^']+)' value/) || message.match(/only \d+ distinct '([^']+)' values/)
  if (m) return `Re-check the '${m[1]}' column mapping when uploading this file, and re-upload with that column correctly filled and unique per row.`

  m = message.match(/^Offering references course '([^']+)' which isn't in courses\.csv/)
  if (m) return `Add course '${m[1]}' to courses.csv, or fix/remove the offering that references it.`

  m = message.match(/^Course '([^']+)' has no eligible faculty in faculty_courses\.csv/)
  if (m) return `Add at least one faculty member qualified to teach '${m[1]}' in faculty_courses.csv.`

  m = message.match(/^Course '([^']+)' has no room matching its required_room_type\/equipment/)
  if (m) return `Add a room matching '${m[1]}''s required room type/equipment, or relax that requirement if it isn't essential.`

  if (/needs a 2-slot session but time_slots\.csv has no contiguous same-day slot pair/.test(message)) {
    return 'Add two back-to-back time slots on the same day in time_slots.csv (a "double period" pair).'
  }

  return null
}
