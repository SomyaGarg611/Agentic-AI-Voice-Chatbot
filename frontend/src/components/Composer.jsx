import { useRef, useState } from 'react'

export default function Composer({ onSend, onUpload, onStop, isBusy, docCount }) {
  const [value, setValue] = useState('')
  const fileRef = useRef(null)

  const submit = () => {
    if (!value.trim()) return
    onSend(value)
    setValue('')
  }

  return (
    <div className="composer">
      <button
        className="composer__icon"
        title="Upload a document (PDF, Word, Excel, PowerPoint, CSV, TXT, MD, HTML)"
        aria-label="Upload a document"
        onClick={() => fileRef.current?.click()}
      >
        <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6">
          <path d="M10 4v12M4 10h12" strokeLinecap="round" />
        </svg>
        {docCount > 0 && <span className="composer__badge">{docCount}</span>}
      </button>
      <input
        ref={fileRef}
        type="file"
        accept=".pdf,.docx,.xlsx,.xlsm,.csv,.tsv,.pptx,.txt,.md,.html,.htm"
        hidden
        onChange={(e) => { onUpload(e.target.files[0]); e.target.value = '' }}
      />

      <input
        className="composer__input"
        type="text"
        value={value}
        placeholder="Ask Aria anything…"
        aria-label="Type your question"
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit() } }}
      />

      {isBusy ? (
        <button className="composer__stop" onClick={onStop} aria-label="Stop (Esc)" title="Stop (Esc)">
          <svg viewBox="0 0 20 20" fill="currentColor"><rect x="6" y="6" width="8" height="8" rx="1.5" /></svg>
        </button>
      ) : (
        <button className="composer__send" onClick={submit} aria-label="Send" disabled={!value.trim()}>
          <svg viewBox="0 0 20 20" fill="currentColor"><path d="M3 10l13-6-5 6 5 6-13-6z" /></svg>
        </button>
      )}
    </div>
  )
}
