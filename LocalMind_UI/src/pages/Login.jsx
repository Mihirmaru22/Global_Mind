import { useState } from 'react'
import { Eye, EyeOff, Loader2, Lock, Moon, ShieldCheck, Sun, User } from 'lucide-react'
import BrandMark from '../components/BrandMark.jsx'
import { useAppStore } from '../store/store.js'
import { useResolvedTheme } from '../utils/theme.js'

export default function Login() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [userFocused, setUserFocused] = useState(false)
  const [passFocused, setPassFocused] = useState(false)

  const loginUser = useAppStore((state) => state.loginUser)
  const loginLoading = useAppStore((state) => state.loginLoading)
  const loginError = useAppStore((state) => state.loginError)
  const settings = useAppStore((state) => state.settings)
  const updateSettings = useAppStore((state) => state.updateSettings)

  const appliedTheme = useResolvedTheme(settings?.theme)

  const handleToggleTheme = () => {
    const nextMode = appliedTheme.mode === 'dark' ? 'light' : 'dark'
    updateSettings({ theme: nextMode })
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!username.trim() || !password || loginLoading) return
    await loginUser(username.trim().toLowerCase(), password)
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        width: '100vw',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'var(--canvas-bg, var(--color-bg))',
        color: 'var(--color-text)',
        padding: '24px',
        boxSizing: 'border-box',
        position: 'relative',
        transition: 'background 0.25s ease, color 0.25s ease',
      }}
    >
      {/* Floating Theme Switcher */}
      <button
        type="button"
        onClick={handleToggleTheme}
        aria-label="Toggle theme"
        title={`Switch to ${appliedTheme.mode === 'dark' ? 'light' : 'dark'} mode`}
        style={{
          position: 'fixed',
          top: '20px',
          right: '20px',
          width: '38px',
          height: '38px',
          borderRadius: 'var(--radius-control, 10px)',
          border: '1px solid var(--color-border)',
          background: 'var(--color-surface)',
          color: 'var(--color-text)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          cursor: 'pointer',
          boxShadow: 'var(--shadow)',
          transition: 'all 0.15s ease',
          zIndex: 20,
        }}
      >
        {appliedTheme.mode === 'dark' ? <Sun size={17} /> : <Moon size={17} />}
      </button>

      {/* Main Login Card */}
      <div
        style={{
          width: '100%',
          maxWidth: '420px',
          background: 'var(--color-surface)',
          border: '1px solid var(--color-border-strong)',
          borderRadius: 'var(--radius-card, 16px)',
          boxShadow: 'var(--shadow)',
          padding: '36px 32px',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: '24px',
          boxSizing: 'border-box',
          backdropFilter: 'blur(12px)',
          transition: 'background 0.25s ease, border-color 0.25s ease',
        }}
      >
        {/* Brand Lockup */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', gap: '6px' }}>
          <div
            style={{
              width: '52px',
              height: '52px',
              borderRadius: '14px',
              background: 'var(--accent-soft, rgba(84, 93, 241, 0.15))',
              border: '1px solid var(--color-border)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              marginBottom: '4px',
            }}
          >
            <BrandMark size={32} />
          </div>
          <h1
            style={{
              fontSize: '22px',
              fontWeight: 600,
              margin: 0,
              letterSpacing: '-0.02em',
              color: 'var(--color-text)',
            }}
          >
            LocalMind
          </h1>
          <p
            style={{
              fontSize: '13px',
              color: 'var(--color-text-muted)',
              margin: 0,
              lineHeight: 1.4,
            }}
          >
            Sign in to access your private data workspace
          </p>
        </div>

        {/* Login Form */}
        <form onSubmit={handleSubmit} style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {loginError && (
            <div
              style={{
                padding: '10px 14px',
                borderRadius: 'var(--radius-control, 10px)',
                background: 'rgba(248, 113, 113, 0.12)',
                border: '1px solid var(--color-danger, #f87171)',
                color: 'var(--color-danger, #f87171)',
                fontSize: '13px',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                lineHeight: 1.4,
              }}
            >
              <span>{loginError}</span>
            </div>
          )}

          {/* Username Field */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <label style={{ fontSize: '13px', fontWeight: 500, color: 'var(--color-text-soft)' }}>
              Username
            </label>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                background: 'var(--color-control, rgba(28, 28, 36, 0.05))',
                border: userFocused
                  ? '1px solid var(--accent)'
                  : '1px solid var(--color-border)',
                boxShadow: userFocused ? '0 0 0 3px var(--accent-soft)' : 'none',
                borderRadius: 'var(--radius-control, 10px)',
                padding: '0 12px',
                gap: '10px',
                height: '42px',
                transition: 'border-color 0.15s ease, box-shadow 0.15s ease',
              }}
            >
              <User size={16} style={{ color: userFocused ? 'var(--accent)' : 'var(--color-text-muted)', flexShrink: 0 }} />
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                onFocus={() => setUserFocused(true)}
                onBlur={() => setUserFocused(false)}
                placeholder="Enter your username"
                required
                autoFocus
                style={{
                  flex: 1,
                  background: 'transparent',
                  border: 'none',
                  outline: 'none',
                  color: 'var(--color-text)',
                  fontSize: '14px',
                  caretColor: 'var(--accent)',
                }}
              />
            </div>
          </div>

          {/* Password Field */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <label style={{ fontSize: '13px', fontWeight: 500, color: 'var(--color-text-soft)' }}>
              Password
            </label>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                background: 'var(--color-control, rgba(28, 28, 36, 0.05))',
                border: passFocused
                  ? '1px solid var(--accent)'
                  : '1px solid var(--color-border)',
                boxShadow: passFocused ? '0 0 0 3px var(--accent-soft)' : 'none',
                borderRadius: 'var(--radius-control, 10px)',
                padding: '0 12px',
                gap: '10px',
                height: '42px',
                transition: 'border-color 0.15s ease, box-shadow 0.15s ease',
              }}
            >
              <Lock size={16} style={{ color: passFocused ? 'var(--accent)' : 'var(--color-text-muted)', flexShrink: 0 }} />
              <input
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onFocus={() => setPassFocused(true)}
                onBlur={() => setPassFocused(false)}
                placeholder="Enter your password"
                required
                style={{
                  flex: 1,
                  background: 'transparent',
                  border: 'none',
                  outline: 'none',
                  color: 'var(--color-text)',
                  fontSize: '14px',
                  caretColor: 'var(--accent)',
                }}
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                tabIndex={-1}
                style={{
                  background: 'transparent',
                  border: 'none',
                  cursor: 'pointer',
                  padding: '4px',
                  color: 'var(--color-text-muted)',
                  display: 'flex',
                  alignItems: 'center',
                  borderRadius: '4px',
                }}
              >
                {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>

          {/* Submit Button */}
          <button
            type="submit"
            disabled={loginLoading || !username.trim() || !password}
            style={{
              marginTop: '6px',
              height: '42px',
              borderRadius: 'var(--radius-control, 10px)',
              background: 'var(--accent)',
              color: 'var(--accent-on, #ffffff)',
              border: 'none',
              fontSize: '14px',
              fontWeight: 600,
              cursor: loginLoading ? 'wait' : 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '8px',
              opacity: loginLoading || !username.trim() || !password ? 0.7 : 1,
              transition: 'background 0.15s ease, opacity 0.15s ease, transform 0.1s ease',
              boxShadow: 'var(--shadow-accent)',
            }}
          >
            {loginLoading ? (
              <>
                <Loader2 size={16} className="spin" />
                <span>Authenticating…</span>
              </>
            ) : (
              'Sign In to Workspace'
            )}
          </button>
        </form>

        {/* Security & Isolation Notice */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            fontSize: '12px',
            color: 'var(--color-text-muted)',
            textAlign: 'center',
            padding: '8px 12px',
            borderRadius: 'var(--radius-control, 10px)',
            background: 'var(--color-control)',
            border: '1px solid var(--color-border)',
          }}
        >
          <ShieldCheck size={16} style={{ color: 'var(--color-success, #34d399)', flexShrink: 0 }} />
          <span>Chat history and documents are strictly isolated per account.</span>
        </div>
      </div>
    </div>
  )
}
