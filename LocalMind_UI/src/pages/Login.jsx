import { useState } from 'react'
import { Eye, EyeOff, Lock, Moon, ShieldCheck, Sun, User } from 'lucide-react'
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
    if (!username.trim() || !password) return
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
        background: 'var(--bg)',
        color: 'var(--text-primary)',
        padding: '24px',
        boxSizing: 'border-box',
        position: 'relative',
        transition: 'background 0.2s ease, color 0.2s ease',
      }}
    >
      {/* Theme Toggle Button */}
      <button
        type="button"
        onClick={handleToggleTheme}
        aria-label="Toggle theme"
        title={`Switch to ${appliedTheme.mode === 'dark' ? 'light' : 'dark'} mode`}
        style={{
          position: 'fixed',
          top: '24px',
          right: '24px',
          width: '40px',
          height: '40px',
          borderRadius: '12px',
          border: '1px solid var(--panel-border)',
          background: 'var(--panel)',
          color: 'var(--text-primary)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          cursor: 'pointer',
          boxShadow: 'var(--shadow)',
          transition: 'all 0.15s ease',
          zIndex: 10,
        }}
      >
        {appliedTheme.mode === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
      </button>

      <div
        style={{
          width: '100%',
          maxWidth: '440px',
          background: 'var(--panel)',
          border: '1px solid var(--panel-border)',
          borderRadius: 'var(--radius-xl, 20px)',
          boxShadow: 'var(--shadow)',
          padding: '40px 36px',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: '24px',
          boxSizing: 'border-box',
          transition: 'background 0.2s ease, border-color 0.2s ease',
        }}
      >
        {/* Brand Header */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', gap: '8px' }}>
          <div
            style={{
              width: '48px',
              height: '48px',
              borderRadius: '14px',
              background: 'var(--primary)',
              color: 'var(--accent-on, #fff)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              marginBottom: '6px',
              boxShadow: '0 4px 12px rgba(168, 93, 63, 0.3)',
            }}
          >
            <BrandMark size={28} />
          </div>
          <h1 style={{ fontSize: '24px', fontWeight: 600, margin: 0, letterSpacing: '-0.02em' }}>
            LocalMind Alpha
          </h1>
          <p style={{ fontSize: '14px', color: 'var(--text-secondary)', margin: 0 }}>
            Sign in to access your private workspace
          </p>
        </div>

        {/* Login Form */}
        <form onSubmit={handleSubmit} style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {loginError && (
            <div
              style={{
                padding: '10px 14px',
                borderRadius: '10px',
                background: 'rgba(168, 77, 66, 0.12)',
                border: '1px solid var(--danger, #a84d42)',
                color: 'var(--danger, #a84d42)',
                fontSize: '13px',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
              }}
            >
              <span>{loginError}</span>
            </div>
          )}

          {/* Username Field */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <label style={{ fontSize: '13px', fontWeight: 500, color: 'var(--text-primary)' }}>
              Username
            </label>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                background: 'var(--input-bg)',
                border: userFocused ? '1px solid var(--primary)' : '1px solid var(--input-border)',
                boxShadow: userFocused ? '0 0 0 3px rgba(168, 93, 63, 0.2)' : 'none',
                borderRadius: '12px',
                padding: '0 12px',
                gap: '10px',
                height: '42px',
                transition: 'border-color 0.15s ease, box-shadow 0.15s ease',
              }}
            >
              <User size={16} style={{ color: userFocused ? 'var(--primary)' : 'var(--text-muted)' }} />
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                onFocus={() => setUserFocused(true)}
                onBlur={() => setUserFocused(false)}
                placeholder="Enter username"
                required
                autoFocus
                style={{
                  flex: 1,
                  background: 'transparent',
                  border: 'none',
                  outline: 'none',
                  color: 'var(--text-primary)',
                  fontSize: '14px',
                  caretColor: 'var(--primary)',
                }}
              />
            </div>
          </div>

          {/* Password Field */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <label style={{ fontSize: '13px', fontWeight: 500, color: 'var(--text-primary)' }}>
              Password
            </label>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                background: 'var(--input-bg)',
                border: passFocused ? '1px solid var(--primary)' : '1px solid var(--input-border)',
                boxShadow: passFocused ? '0 0 0 3px rgba(168, 93, 63, 0.2)' : 'none',
                borderRadius: '12px',
                padding: '0 12px',
                gap: '10px',
                height: '42px',
                transition: 'border-color 0.15s ease, box-shadow 0.15s ease',
              }}
            >
              <Lock size={16} style={{ color: passFocused ? 'var(--primary)' : 'var(--text-muted)' }} />
              <input
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onFocus={() => setPassFocused(true)}
                onBlur={() => setPassFocused(false)}
                placeholder="Enter password"
                required
                style={{
                  flex: 1,
                  background: 'transparent',
                  border: 'none',
                  outline: 'none',
                  color: 'var(--text-primary)',
                  fontSize: '14px',
                  caretColor: 'var(--primary)',
                }}
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                style={{
                  background: 'transparent',
                  border: 'none',
                  cursor: 'pointer',
                  padding: '4px',
                  color: 'var(--text-muted)',
                  display: 'flex',
                  alignItems: 'center',
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
              marginTop: '8px',
              height: '44px',
              borderRadius: '12px',
              background: 'var(--primary)',
              color: '#fff',
              border: 'none',
              fontSize: '14px',
              fontWeight: 600,
              cursor: loginLoading ? 'wait' : 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '8px',
              opacity: loginLoading || !username.trim() || !password ? 0.7 : 1,
              transition: 'background 0.15s ease',
            }}
          >
            {loginLoading ? 'Authenticating…' : 'Sign In to Workspace'}
          </button>
        </form>

        {/* Security / Isolation notice */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            fontSize: '12px',
            color: 'var(--text-muted)',
            textAlign: 'center',
          }}
        >
          <ShieldCheck size={16} style={{ color: 'var(--success, #4f7a5a)', flexShrink: 0 }} />
          <span>Chat history and uploaded documents are strictly isolated per account.</span>
        </div>
      </div>
    </div>
  )
}
