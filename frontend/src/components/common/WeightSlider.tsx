import styles from './WeightSlider.module.css'

export function WeightSlider({
  label,
  value,
  max = 10,
  onChange,
}: {
  label: string
  value: number
  max?: number
  onChange: (v: number) => void
}) {
  return (
    <div className={styles.row}>
      <span className={styles.label}>{label}</span>
      <input
        className={styles.slider}
        type="range"
        min={0}
        max={max}
        step={1}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-label={label}
      />
      <span className={`${styles.value} mono`}>{value}</span>
    </div>
  )
}
