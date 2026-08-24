import styles from './BarChart.module.css'

export interface BarChartBar {
  label: string
  value: number
  tone?: 'ok' | 'warn' | 'accent'
}

/** Minimal hand-rolled column chart — no charting library. One hue per bar
 * when tone encodes status (good/warn), a single accent hue when it's one
 * plain-magnitude series (see dataviz skill: "when a series means good/bad
 * it wears status tokens; when it's just a magnitude series it wears one
 * hue, no legend needed"). Value sits at the bar's cap, category label
 * below the baseline — both always visible, so color is never the only
 * channel carrying the value. */
export function BarChart({ bars, height = 120 }: { bars: BarChartBar[]; height?: number }) {
  const max = Math.max(1, ...bars.map((b) => b.value))
  return (
    <div className={styles.chart} style={{ height: `${height}px` }}>
      {bars.map((b) => (
        <div key={b.label} className={styles.col} title={`${b.label}: ${b.value}`}>
          <span className={`${styles.value} mono`}>{b.value}</span>
          <div className={styles.track}>
            <div
              className={`${styles.bar} ${styles[b.tone ?? 'accent']}`}
              style={{ height: `${(b.value / max) * 100}%` }}
            />
          </div>
          <span className={styles.label}>{b.label}</span>
        </div>
      ))}
    </div>
  )
}
