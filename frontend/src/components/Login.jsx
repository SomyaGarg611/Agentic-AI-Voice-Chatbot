import { useEffect, useRef, useState } from 'react'

export default function Login({ config, onGoogle, onDev, error }) {
  const [email, setEmail] = useState('')
  const googleBtn = useRef(null)
  const hasGoogle = !!config.googleClientId

  // Load Google Identity Services and render the official button
  useEffect(() => {
    if (!hasGoogle) return
    const render = () => {
      if (!window.google?.accounts?.id || !googleBtn.current) return
      window.google.accounts.id.initialize({
        client_id: config.googleClientId,
        callback: (resp) => onGoogle(resp.credential),
      })
      window.google.accounts.id.renderButton(googleBtn.current, {
        theme: 'filled_black', size: 'large', shape: 'pill', width: 280,
      })
    }
    if (window.google?.accounts?.id) { render(); return }
    const s = document.createElement('script')
    s.src = 'https://accounts.google.com/gsi/client'
    s.async = true
    s.defer = true
    s.onload = render
    document.head.appendChild(s)
  }, [hasGoogle, config.googleClientId, onGoogle])

  return (
    <div className="login">
      <div className="login__card">
        <span className="login__mark" aria-hidden="true" />
        <h1 className="login__title">Aria</h1>
        <p className="login__sub">Sign in to start researching by voice.</p>

        {hasGoogle && <div ref={googleBtn} className="login__google" />}

        {config.devLogin && (
          <form onSubmit={(e) => { e.preventDefault(); if (email.trim()) onDev(email.trim()) }}>
            <input
              className="login__input"
              type="email"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoFocus
              aria-label="Email"
            />
            <button className="login__btn" type="submit" disabled={!email.trim()}>
              Continue
            </button>
            <p className="login__hint">Dev sign-in (Google not configured)</p>
          </form>
        )}

        {error && <p className="login__error">{error}</p>}
      </div>
    </div>
  )
}
