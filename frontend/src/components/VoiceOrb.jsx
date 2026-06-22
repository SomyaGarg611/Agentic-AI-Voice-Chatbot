import { STATE } from '../useVoiceSession'

/**
 * The signature element: a state-reactive voice orb.
 * Colour + motion encode the agent's state, so the orb itself tells you
 * what Aria is doing — listening, thinking, or speaking.
 */
export default function VoiceOrb({ phase, isListening, disabled, onClick }) {
  const label =
    phase === STATE.LISTENING ? 'Stop listening'
    : isListening ? 'Stop listening'
    : 'Start talking'

  return (
    <button
      className={`orb orb--${phase}`}
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      aria-pressed={isListening}
      title={label}
    >
      <span className="orb__ring orb__ring--1" aria-hidden="true" />
      <span className="orb__ring orb__ring--2" aria-hidden="true" />
      <span className="orb__core" aria-hidden="true">
        {isListening ? (
          <span className="orb__wave">
            <i /><i /><i /><i /><i />
          </span>
        ) : (
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z" />
            <path d="M19 11v1a7 7 0 0 1-14 0v-1" strokeLinecap="round" />
            <line x1="12" y1="19" x2="12" y2="23" strokeLinecap="round" />
          </svg>
        )}
      </span>
    </button>
  )
}
