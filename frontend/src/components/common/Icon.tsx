export type IconName =
  | 'grid'
  | 'upload'
  | 'calendar'
  | 'play'
  | 'users'
  | 'cap'
  | 'door'
  | 'book'
  | 'alert'
  | 'chart'
  | 'gear'
  | 'check'
  | 'sun'
  | 'moon'
  | 'arrowRight'
  | 'download'
  | 'print'

const common = {
  width: 18,
  height: 18,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.8,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
}

export function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  const props = { ...common, width: size, height: size }
  switch (name) {
    case 'grid':
      return (
        <svg {...props}>
          <rect x="3" y="3" width="8" height="8" rx="1.5" />
          <rect x="13" y="3" width="8" height="8" rx="1.5" />
          <rect x="3" y="13" width="8" height="8" rx="1.5" />
          <rect x="13" y="13" width="8" height="8" rx="1.5" />
        </svg>
      )
    case 'upload':
      return (
        <svg {...props}>
          <path d="M12 16V4M12 4l-4 4M12 4l4 4" />
          <path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" />
        </svg>
      )
    case 'calendar':
      return (
        <svg {...props}>
          <rect x="3" y="5" width="18" height="16" rx="2" />
          <path d="M3 10h18M8 3v4M16 3v4" />
        </svg>
      )
    case 'play':
      return (
        <svg {...props}>
          <path d="M7 4.5v15l13-7.5-13-7.5z" />
        </svg>
      )
    case 'users':
      return (
        <svg {...props}>
          <circle cx="9" cy="8" r="3.2" />
          <path d="M3.5 20a5.5 5.5 0 0 1 11 0" />
          <path d="M16 8.2a3 3 0 1 1 3.6 4.7" />
          <path d="M15 14.2c2.9.4 5 2.6 5 5.8" />
        </svg>
      )
    case 'cap':
      return (
        <svg {...props}>
          <path d="M2 9l10-4 10 4-10 4-10-4z" />
          <path d="M6 11v4c0 1.4 2.7 3 6 3s6-1.6 6-3v-4" />
          <path d="M22 9v6" />
        </svg>
      )
    case 'door':
      return (
        <svg {...props}>
          <rect x="5" y="3" width="14" height="18" rx="1" />
          <circle cx="14.5" cy="12" r="1" fill="currentColor" stroke="none" />
        </svg>
      )
    case 'book':
      return (
        <svg {...props}>
          <path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H12v18H6.5A2.5 2.5 0 0 0 4 23V5.5z" />
          <path d="M20 5.5A2.5 2.5 0 0 0 17.5 3H12v18h5.5a2.5 2.5 0 0 1 2.5 2V5.5z" />
        </svg>
      )
    case 'alert':
      return (
        <svg {...props}>
          <path d="M10.3 3.9L1.9 18a2 2 0 0 0 1.7 3h16.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" />
          <path d="M12 9v4M12 17h.01" />
        </svg>
      )
    case 'chart':
      return (
        <svg {...props}>
          <path d="M4 20V10M11 20V4M18 20v-7" />
          <path d="M3 20h18" />
        </svg>
      )
    case 'gear':
      return (
        <svg {...props}>
          <circle cx="12" cy="12" r="3.2" />
          <path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1" />
        </svg>
      )
    case 'check':
      return (
        <svg {...props}>
          <circle cx="12" cy="12" r="9" />
          <path d="M8.5 12.5l2.4 2.4L16 10" />
        </svg>
      )
    case 'sun':
      return (
        <svg {...props}>
          <circle cx="12" cy="12" r="4.2" />
          <path d="M12 2.5v2.4M12 19v2.5M4.9 4.9l1.7 1.7M17.4 17.4l1.7 1.7M2.5 12h2.4M19 12h2.5M4.9 19.1l1.7-1.7M17.4 6.6l1.7-1.7" />
        </svg>
      )
    case 'moon':
      return (
        <svg {...props}>
          <path d="M20 14.5A8.5 8.5 0 1 1 9.5 4a7 7 0 0 0 10.5 10.5z" />
        </svg>
      )
    case 'arrowRight':
      return (
        <svg {...props}>
          <path d="M4 12h15M13 6l6 6-6 6" />
        </svg>
      )
    case 'download':
      return (
        <svg {...props}>
          <path d="M12 4v12M12 16l-4-4M12 16l4-4" />
          <path d="M4 18v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" />
        </svg>
      )
    case 'print':
      return (
        <svg {...props}>
          <path d="M6 9V3h12v6" />
          <rect x="4" y="9" width="16" height="8" rx="1.5" />
          <path d="M6 14h12v7H6z" />
        </svg>
      )
  }
}
