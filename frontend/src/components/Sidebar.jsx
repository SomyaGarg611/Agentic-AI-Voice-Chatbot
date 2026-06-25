function timeAgo(iso) {
  if (!iso) return ''
  const then = new Date(iso.replace(' ', 'T') + 'Z').getTime()
  const s = Math.max(0, (Date.now() - then) / 1000)
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

export default function Sidebar({ open, chats, activeChatId, onClose, onNew, onOpen, onDelete }) {
  return (
    <>
      <div className={`scrim ${open ? 'scrim--on' : ''}`} onClick={onClose} aria-hidden="true" />
      <aside className={`sidebar ${open ? 'sidebar--on' : ''}`} aria-label="Chat history">
        <div className="sidebar__head">
          <span className="sidebar__title">Chats</span>
          <button className="sidebar__close" onClick={onClose} aria-label="Close history">
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6"><path d="M4 4l8 8M12 4l-8 8" strokeLinecap="round" /></svg>
          </button>
        </div>

        <button className="newchat" onClick={onNew}>
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6"><path d="M8 3v10M3 8h10" strokeLinecap="round" /></svg>
          New chat
        </button>

        <div className="sidebar__list">
          {chats.length === 0 && <p className="sidebar__empty">No past chats yet.</p>}
          {chats.map((c) => (
            <div
              key={c.id}
              className={`chatitem ${c.id === activeChatId ? 'chatitem--active' : ''}`}
              onClick={() => onOpen(c.id)}
            >
              <div className="chatitem__body">
                <span className="chatitem__title">{c.title}</span>
                <span className="chatitem__meta">{timeAgo(c.updated_at)} · {c.turns} turn{c.turns === 1 ? '' : 's'}</span>
              </div>
              <button
                className="chatitem__del"
                onClick={(e) => { e.stopPropagation(); onDelete(c.id) }}
                aria-label="Delete chat"
                title="Delete chat"
              >
                <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M3 5h10M6.5 5V3.5h3V5M5 5l.5 8h5l.5-8" strokeLinecap="round" strokeLinejoin="round" /></svg>
              </button>
            </div>
          ))}
        </div>
      </aside>
    </>
  )
}
