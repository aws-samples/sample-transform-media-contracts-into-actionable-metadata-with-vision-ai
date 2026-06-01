import { useState, useEffect } from 'react'
import { useAuth } from 'react-oidc-context'
import Header from './components/Header.jsx'
import Home from './components/Home.jsx'
import Chat from './components/Chat.jsx'
import KBChat from './components/KBChat.jsx'
import LegalTeam from './components/LegalTeam.jsx'
import ResultsBrowser from './components/ResultsBrowser.jsx'
import JobStatus from './components/JobStatus.jsx'
import CostCalculator from './components/CostCalculator.jsx'

const COGNITO_DOMAIN = import.meta.env.VITE_COGNITO_DOMAIN
const CLIENT_ID = import.meta.env.VITE_COGNITO_CLIENT_ID
const LOGOUT_URI = `${window.location.origin}/`

const TABS = [
    { id: 'home', label: '🏠 Home' },
    { id: 'team', label: '⚖️ Legal Team Builder' },
    { id: 'chat', label: '💬 Chat' },
    { id: 'jobs', label: '📋 Jobs' },
    { id: 'results', label: '📊 Results' },
    { id: 'kb', label: '📚 KB Chat' },
    { id: 'calculator', label: '🧮 Cost Calculator' },
]

export default function App() {
    const auth = useAuth()
    const [tab, setTab] = useState('home')
    const [branding, setBranding] = useState({})
    const [theme, setTheme] = useState(() => localStorage.getItem('media-theme') || '')
    function applyTheme(t) {
        setTheme(t)
        localStorage.setItem('media-theme', t)
        document.documentElement.setAttribute('data-theme', t)
    }

    useEffect(() => {
        fetch('/api/env')
            .then(r => r.json())
            .then(data => {
                if (data.branding) {
                    setBranding(data.branding)
                    document.title = data.branding.appName || 'Media Contracts'
                    const saved = localStorage.getItem('media-theme')
                    applyTheme(saved || data.branding.theme || 'aws-purple')
                }
            })
            .catch(() => {
                fetch('/config/branding.json')
                    .then(r => r.json())
                    .then(data => {
                        setBranding(data)
                        document.title = data.appName || 'Media Contracts'
                        const saved = localStorage.getItem('media-theme')
                        applyTheme(saved || data.theme || 'aws-purple')
                    })
                    .catch(() => {})
            })
    }, [])

    function handleLogout() {
        auth.removeUser()
        window.location.href = `${COGNITO_DOMAIN}/logout?client_id=${CLIENT_ID}&logout_uri=${encodeURIComponent(LOGOUT_URI)}`
    }

    if (auth.isLoading) {
        return (
            <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <div className="loading-dots">
                    <span /><span /><span />
                </div>
            </div>
        )
    }

    if (auth.error) {
        return (
            <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <div className="card" style={{ padding: 24, maxWidth: 400, textAlign: 'center' }}>
                    <div style={{ fontSize: 28, marginBottom: 8 }}>⚠️</div>
                    <div style={{ fontSize: 14, marginBottom: 12 }}>Authentication error</div>
                    <div style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: 16 }}>{auth.error.message}</div>
                    <button className="primary" onClick={() => auth.signinRedirect()}>Try again</button>
                </div>
            </div>
        )
    }

    if (!auth.isAuthenticated) {
        return (
            <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--bg-gradient, var(--bg))' }}>
                <div className="card" style={{ width: 360, padding: 32, textAlign: 'center' }}>
                    <div style={{ fontSize: 28, marginBottom: 4 }}>🔒</div>
                    <div style={{ fontSize: 16, fontWeight: 600 }}>
                        {branding.appName || 'Media Contracts'}
                    </div>
                    <div style={{ fontSize: 12, color: 'var(--text-dim)', margin: '8px 0 20px' }}>
                        Sign in to continue
                    </div>
                    <button className="primary" style={{ width: '100%', padding: '8px 0', fontSize: 13 }}
                        onClick={() => auth.signinRedirect()}>
                        Sign In with Cognito
                    </button>
                </div>
            </div>
        )
    }

    return (
        <div className="container">
            <Header
                branding={branding}
                theme={theme}
                onThemeChange={applyTheme}
                onLogout={handleLogout}
                userEmail={auth.user?.profile?.email}
            />
            <nav style={{ marginBottom: 20 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                    {TABS.map(({ id, label }) => (
                        <button key={id} onClick={() => setTab(id)}
                            className={tab === id ? 'tab-active' : ''}
                            style={{ fontSize: 12 }}>
                            {label}
                        </button>
                    ))}
                </div>
            </nav>

            {tab === 'home' && <Home onNavigate={setTab} branding={branding} />}
            {tab === 'chat' && <Chat accessToken={auth.user?.access_token} />}
            {tab === 'jobs' && <JobStatus onNavigateToResults={(prefix) => { setTab('results') }} accessToken={auth.user?.access_token} />}
            {tab === 'results' && <ResultsBrowser accessToken={auth.user?.access_token} />}
            {tab === 'kb' && <KBChat accessToken={auth.user?.access_token} />}
            {tab === 'calculator' && <CostCalculator accessToken={auth.user?.access_token} />}
            <div style={{ display: tab === 'team' ? 'block' : 'none' }}>
                <LegalTeam accessToken={auth.user?.access_token} />
            </div>
        </div>
    )
}
