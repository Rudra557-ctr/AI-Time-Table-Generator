import { useEffect, useState } from 'react'
import { Icon } from '../common/Icon'
import styles from './ThemeToggle.module.css'

const KEY = 'sih-timetable-theme'

function readStoredTheme(): 'light' | 'dark' | null {
  try {
    const v = localStorage.getItem(KEY)
    return v === 'light' || v === 'dark' ? v : null
  } catch {
    return null
  }
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<'light' | 'dark' | null>(() => readStoredTheme())

  useEffect(() => {
    const root = document.documentElement
    if (theme) root.setAttribute('data-theme', theme)
    else root.removeAttribute('data-theme')
    try {
      if (theme) localStorage.setItem(KEY, theme)
      else localStorage.removeItem(KEY)
    } catch {
      // ignore
    }
  }, [theme])

  const prefersDark =
    typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches
  const effectiveDark = theme ? theme === 'dark' : prefersDark

  return (
    <button
      type="button"
      className={styles.toggle}
      onClick={() => setTheme(effectiveDark ? 'light' : 'dark')}
      aria-label={effectiveDark ? 'Switch to light mode' : 'Switch to dark mode'}
    >
      <Icon name={effectiveDark ? 'sun' : 'moon'} size={16} />
    </button>
  )
}
