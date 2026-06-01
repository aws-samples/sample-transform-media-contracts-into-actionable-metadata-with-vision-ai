import { useState } from 'react'

export default function Login({ onLogin, branding = {} }) {
    const [user, setUser] = useState('')
    const [pass, setPass] = useState('')
    const [error, setError] = useState('')
    const [shake, setShake] = useState(false)

    function handleSubmit(e) {
        e.preventDefault()
        if (user === 'admin' && pass === 'admin') {
            onLogin()
        } else {
            setError('Invalid credentials')
            setShake(true)
            setTimeout(() => setShake(false), 500)
        }
    }

    return (
        <div style={{
            minHeight: '100vh',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: 'var(--bg-gradient, var(--bg))',
        }}>
            <form onSubmit={handleSubmit} className={`card ${shake ? 'login-shake' : ''}`} style={{
                width: 360,
                padding: 32,
                display: 'flex',
                flexDirection: 'column',
                gap: 16,
            }}>
                <div style={{ textAlign: 'center', marginBottom: 8 }}>
                    <div style={{ fontSize: 28, marginBottom: 4 }}>🔒</div>
                    <div style={{ fontSize: 16, fontWeight: 600 }}>
                        {branding.appName || 'Media Contracts'}
                    </div>
                    <div style={{ fontSize: 12, color: 'var(--text-dim)', marginTop: 4 }}>
                        Sign in to continue
                    </div>
                </div>

                <div>
                    <label style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: 4, display: 'block' }}>
                        Username
                    </label>
                    <input
                        type="text"
                        value={user}
                        onChange={e => setUser(e.target.value)}
                        autoFocus
                        placeholder="Enter username"
                    />
                </div>

                <div>
                    <label style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: 4, display: 'block' }}>
                        Password
                    </label>
                    <input
                        type="password"
                        value={pass}
                        onChange={e => setPass(e.target.value)}
                        placeholder="Enter password"
                    />
                </div>

                {error && (
                    <div style={{ fontSize: 12, color: 'var(--red)', textAlign: 'center' }}>
                        {error}
                    </div>
                )}

                <button type="submit" className="primary" style={{ width: '100%', padding: '8px 0', fontSize: 13 }}>
                    Sign In
                </button>
            </form>
        </div>
    )
}
