import { useState, useRef, useEffect } from 'react'

const THEMES = [
    { id: 'aws-purple', label: '🟣 AWS Purple' },
]

const WIDTHS = [
    { id: '960px',  label: 'S' },
    { id: '1200px', label: 'M' },
    { id: '1600px', label: 'L' },
    { id: '100%',   label: 'Full' },
]

const SCALES = [
    { id: '1',    label: '100%' },
    { id: '1.15', label: '115%' },
    { id: '1.3',  label: '130%' },
    { id: '1.5',  label: '150%' },
]

export default function Header({ branding = {}, theme = 'aws-purple', onThemeChange, onLogout, userEmail }) {
    const name = branding.appName || ''
    const emoji = branding.appEmoji || '📄'
    const logo = branding.appLogo || ''
    const logoHeight = branding.appLogoHeight || 32
    const subtitle = branding.appSubtitle || ''

    const [menuOpen, setMenuOpen] = useState(false)
    const menuRef = useRef(null)
    const [width, setWidth] = useState(() => localStorage.getItem('media-layout-width') || '1200px')
    const [scale, setScale] = useState(() => localStorage.getItem('media-layout-scale') || '1')

    useEffect(() => {
        document.documentElement.style.setProperty('--layout-width', width)
        document.documentElement.style.setProperty('--layout-scale', scale)
        applyScale(scale)
    }, [])

    function applyWidth(w) {
        setWidth(w)
        localStorage.setItem('media-layout-width', w)
        document.documentElement.style.setProperty('--layout-width', w)
    }

    function applyScale(s) {
        setScale(s)
        localStorage.setItem('media-layout-scale', s)
        document.documentElement.style.setProperty('--layout-scale', s)
        const f = parseFloat(s)
        const root = document.documentElement.style
        root.setProperty('--fs-xs',   `${Math.round(10 * f)}px`)
        root.setProperty('--fs-sm',   `${Math.round(11 * f)}px`)
        root.setProperty('--fs-mono', `${Math.round(12 * f)}px`)
        root.setProperty('--fs-base', `${Math.round(13 * f)}px`)
        root.setProperty('--fs-md',   `${Math.round(14 * f)}px`)
        root.setProperty('--fs-lg',   `${Math.round(16 * f)}px`)
        root.setProperty('--fs-xl',   `${Math.round(18 * f)}px`)
        root.setProperty('--fs-2xl',  `${Math.round(22 * f)}px`)
        root.setProperty('--fs-3xl',  `${Math.round(28 * f)}px`)
    }

    useEffect(() => {
        function handleClick(e) {
            if (menuRef.current && !menuRef.current.contains(e.target)) setMenuOpen(false)
        }
        document.addEventListener('mousedown', handleClick)
        return () => document.removeEventListener('mousedown', handleClick)
    }, [])

    return (
        <div style={{ marginBottom: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <div>
                <h1 style={{ fontSize: 'var(--fs-2xl)', fontWeight: 600, display: 'flex', alignItems: 'center', gap: 10 }}>
                    {logo
                        ? <img src={logo} alt="" style={{ height: logoHeight }} />
                        : <span style={{ fontSize: 'var(--fs-3xl)' }}>{emoji}</span>
                    } {name}
                </h1>
                {subtitle && (
                    <p style={{ color: 'var(--text-dim)', fontSize: 'var(--fs-base)', marginTop: 4 }}>{subtitle}</p>
                )}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                {/* Layout width */}
                <div style={{ display: 'flex', gap: 2, background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 6, padding: 2 }}>
                    {WIDTHS.map(w => (
                        <button key={w.id} onClick={() => applyWidth(w.id)} style={{
                            fontSize: 'var(--fs-sm)', padding: '2px 7px',
                            background: width === w.id ? 'var(--accent-bg)' : 'none',
                            border: 'none', borderRadius: 4,
                            color: width === w.id ? '#fff' : 'var(--text-dim)',
                        }}>
                            {w.label}
                        </button>
                    ))}
                </div>

                {/* Font scale */}
                <div style={{ display: 'flex', gap: 2, background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 6, padding: 2 }}>
                    {SCALES.map(s => (
                        <button key={s.id} onClick={() => applyScale(s.id)} style={{
                            fontSize: 'var(--fs-sm)', padding: '2px 7px',
                            background: scale === s.id ? 'var(--accent-bg)' : 'none',
                            border: 'none', borderRadius: 4,
                            color: scale === s.id ? '#fff' : 'var(--text-dim)',
                        }}>
                            {s.label}
                        </button>
                    ))}
                </div>

                <select
                    value={theme}
                    onChange={e => onThemeChange?.(e.target.value)}
                    className="theme-toggle"
                    style={{ width: 'auto' }}
                >
                    {THEMES.map(t => (
                        <option key={t.id} value={t.id}>{t.label}</option>
                    ))}
                </select>

                <div ref={menuRef} style={{ position: 'relative' }}>
                    <button
                        onClick={() => setMenuOpen(v => !v)}
                        className="user-avatar-btn"
                        aria-label="User menu"
                    >
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <circle cx="12" cy="8" r="4" />
                            <path d="M20 21a8 8 0 1 0-16 0" />
                        </svg>
                    </button>
                    {menuOpen && (
                        <div className="user-menu-dropdown">
                            <div style={{ padding: '8px 12px', fontSize: 'var(--fs-mono)', color: 'var(--text-dim)', borderBottom: '1px solid var(--border)' }}>
                                {userEmail || 'User'}
                            </div>
                            <button
                                onClick={() => { setMenuOpen(false); onLogout?.() }}
                                className="user-menu-item"
                            >
                                Logout
                            </button>
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}
