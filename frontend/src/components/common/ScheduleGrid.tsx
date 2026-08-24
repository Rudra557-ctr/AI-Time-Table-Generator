import type { ClassGrid } from '../../utils/csv'
import styles from './ScheduleGrid.module.css'

export function ScheduleGrid({
  grid,
  isCellChanged,
}: {
  grid: ClassGrid
  isCellChanged?: (cell: string) => boolean
}) {
  return (
    <div className={styles.scroller}>
      <table className={styles.grid}>
        <thead>
          <tr>
            <th className={styles.dayHead}>Day</th>
            {grid.periodHeaders.map((h) => (
              <th key={h} className="mono">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {grid.rows.map((row, ri) => (
            <tr key={row.day} className={ri % 2 === 1 ? styles.rowAlt : ''}>
              <td className={styles.dayCell}>{row.day}</td>
              {row.cells.map((cell, i) => {
                const changedHere = cell !== '—' && isCellChanged?.(cell)
                return (
                  <td
                    key={i}
                    className={`${styles.slotCell} mono ${cell === '—' ? styles.empty : ''} ${changedHere ? styles.changedCell : ''}`}
                  >
                    {cell}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
