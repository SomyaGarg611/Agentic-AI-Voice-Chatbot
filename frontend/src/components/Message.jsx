const TOOL_TEXT = {
  web_search: 'Searching the web',
  fetch_url: 'Reading a source',
  rag_search: 'Checking your documents',
  calculator: 'Calculating',
}

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function format(text) {
  let out = escapeHtml(text)
  out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  out = out.replace(/\[(\d+)\]\s*(https?:\/\/\S+)/g,
    (_, n, url) => `<a href="${url}" target="_blank" rel="noopener noreferrer">[${n}]</a>`)
  return out
}

export default function Message({ role, text, pending, tool }) {
  const isUser = role === 'user'
  return (
    <div className={`msg msg--${role}`}>
      <div className="msg__avatar" aria-hidden="true">
        {isUser ? 'You' : <span className="msg__spark" />}
      </div>
      <div className="msg__bubble">
        {pending ? (
          <span className="msg__pending">
            <span className="dots"><i /><i /><i /></span>
            <span className="msg__tool">{tool ? TOOL_TEXT[tool] || 'Thinking' : 'Thinking'}…</span>
          </span>
        ) : (
          <span dangerouslySetInnerHTML={{ __html: format(text) }} />
        )}
      </div>
    </div>
  )
}
