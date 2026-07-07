import { useEffect, useRef, useState } from 'react'
import { useVoiceSession, STATE } from './useVoiceSession'
import VoiceOrb from './components/VoiceOrb'
import Message from './components/Message'
import Composer from './components/Composer'
import Toasts from './components/Toasts'
import Sidebar from './components/Sidebar'
import Login from './components/Login'

const SUGGESTIONS = [
  "What's the latest on AI regulation?",
  'Summarise my uploaded document',
  'What is 2.5 million divided by 7?',
]

export default function App() {
  const s = useVoiceSession()
  const scrollRef = useRef(null)
  const [navOpen, setNavOpen] = useState(false)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [s.messages, s.transcript])

  const empty = s.messages.length === 0
  const connecting = s.phase === STATE.CONNECTING

  const openHistory = () => { s.loadChats(); setNavOpen(true) }

  if (s.needAuth) return <Login config={s.authConfig} onGoogle={s.loginGoogle} onDev={s.loginDev} error={s.authError} />

  return (
    <div className="app">
      <Sidebar
        open={navOpen}
        chats={s.chats}
        activeChatId={s.activeChatId}
        onClose={() => setNavOpen(false)}
        onNew={() => { s.newChat(); setNavOpen(false) }}
        onOpen={(id) => { s.openChat(id); setNavOpen(false) }}
        onDelete={s.deleteChat}
      />

      <header className="topbar">
        <div className="brand">
          <button className="iconbtn" onClick={openHistory} aria-label="Chat history" title="Chat history">
            <svg viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.6"><path d="M3 5h12M3 9h12M3 13h12" strokeLinecap="round" /></svg>
          </button>
          <span className="brand__mark" aria-hidden="true" />
          <span className="brand__name">Aria</span>
          <span className="brand__role">Research Analyst</span>
        </div>
        <div className="topbar__right">
          <button className="iconbtn" onClick={() => s.newChat()} aria-label="New chat" title="New chat">
            <svg viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.6"><path d="M9 4v10M4 9h10" strokeLinecap="round" /></svg>
          </button>
          <div className={`pill pill--${s.phase}`}>
            <span className="pill__dot" />
            <span className="pill__text">{s.statusText}</span>
          </div>
          {s.user && (
            <button className="userchip" onClick={s.logout} title={`${s.user.email} — click to sign out`} aria-label="Sign out">
              {s.user.picture
                ? <img src={s.user.picture} alt="" referrerPolicy="no-referrer" />
                : <span className="userchip__initial">{(s.user.name || s.user.email || '?')[0].toUpperCase()}</span>}
            </button>
          )}
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
