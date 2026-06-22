import { useEffect, useRef } from 'react'
import { useVoiceSession, STATE } from './useVoiceSession'
import VoiceOrb from './components/VoiceOrb'
import Message from './components/Message'
import Composer from './components/Composer'
import Toasts from './components/Toasts'

const SUGGESTIONS = [
  "What's the latest on AI regulation?",
  'Summarise my uploaded document',
  'What is 2.5 million divided by 7?',
]

export default function App() {
  const s = useVoiceSession()
  const scrollRef = useRef(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [s.messages, s.transcript])

  const empty = s.messages.length === 0
  const connecting = s.phase === STATE.CONNECTING

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand__mark" aria-hidden="true" />
          <span className="brand__name">Aria</span>
          <span className="brand__role">Research Analyst</span>
        </div>
        <div className={`pill pill--${s.phase}`}>
          <span className="pill__dot" />
          <span className="pill__text">{s.statusText}</span>
        </div>
      </header>

      <main className="stage" ref={scrollRef}>
        {empty ? (
          <section className="hero">
            <h1 className="hero__title">Talk to a research analyst.</h1>
            <p className="hero__sub">
              Aria listens, searches the web, reads documents you share, runs the numbers,
              and answers out loud — with sources.
            </p>
            <div className="hero__chips">
              {SUGGESTIONS.map((q) => (
                <button key={q} className="chip" onClick={() => s.sendText(q)}>{q}</button>
              ))}
            </div>
          </section>
        ) : (
          <div className="thread">
            {s.messages.map((m) => (
              <Message key={m.id} role={m.role} text={m.text} pending={m.pending} tool={m.tool} />
            ))}
          </div>
        )}
      </main>

      <div className={`transcript ${s.transcript ? 'transcript--on' : ''}`} aria-live="polite">
        {s.transcript}
      </div>

      <footer className="console">
        <VoiceOrb
          phase={s.phase}
          isListening={s.isListening}
          disabled={connecting}
          onClick={s.toggleMic}
        />
        <Composer
          onSend={s.sendText}
          onUpload={s.uploadFile}
          onStop={s.stopAgent}
          isBusy={s.isBusy}
          docCount={s.docCount}
        />
      </footer>

      <Toasts toasts={s.toasts} />
    </div>
  )
}
