const ICONS = {
  success: <path d="M4 8.5l3 3 5-6" strokeLinecap="round" strokeLinejoin="round" />,
  error: <><circle cx="8" cy="8" r="6.5" /><path d="M8 4.5v4M8 11h.01" strokeLinecap="round" /></>,
  info: <><circle cx="8" cy="8" r="6.5" /><path d="M8 7.5v4M8 5h.01" strokeLinecap="round" /></>,
}

export default function Toasts({ toasts }) {
  return (
    <div className="toasts" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`toast toast--${t.type}`}>
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6">
            {ICONS[t.type] || ICONS.info}
          </svg>
          <span>{t.message}</span>
        </div>
      ))}
    </div>
  )
}
