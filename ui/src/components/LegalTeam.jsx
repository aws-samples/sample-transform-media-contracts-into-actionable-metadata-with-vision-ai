import React, { useState, useEffect } from 'react'

const CATEGORIES = ['Core Specialists', 'Experimental']

function label(name) {
    return name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

export default function LegalTeam({ onSave, accessToken }) {
    const [specialists, setSpecialists] = useState([])
    const [enabled, setEnabled] = useState({})
    const [agentMode, setAgentMode] = useState(false)
    const [agentModeLocked, setAgentModeLocked] = useState(false)
    const [saved, setSaved] = useState(false)
    const [loading, setLoading] = useState(true)

    const authHeaders = accessToken
        ? { 'Authorization': `Bearer ${accessToken}` }
        : {};

    useEffect(() => {
        Promise.all([
            fetch('/api/specialists', { headers: authHeaders }).then(r => r.json()),
            fetch('/api/pipeline-config', { headers: authHeaders }).then(r => r.json()),
        ]).then(([specData, configData]) => {
            const list = specData.specialists || []
            const enabledList = configData.enabled_specialists || []
            const map = {}
            for (const s of list) {
                map[s.id] = enabledList.includes(s.id)
            }
            setSpecialists(list)
            setEnabled(map)
            setAgentMode(!!configData.agent_mode)
            setAgentModeLocked(!!configData.agent_mode_locked)
            setLoading(false)
        }).catch(() => {
            setLoading(false)
        })
    }, [])

    const saveConfig = async (enabledMap, newAgentMode) => {
        const enabledList = specialists.filter(s => enabledMap[s.id]).map(s => s.id)
        const availableList = specialists.map(s => s.id)
        try {
            await fetch('/api/pipeline-config', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json', ...authHeaders },
                body: JSON.stringify({
                    agent_mode: newAgentMode,
                    enabled_specialists: enabledList,
                    available_specialists: availableList,
                }),
            })
            setSaved(true)
            setTimeout(() => setSaved(false), 1500)
        } catch (e) {
            console.error('Failed to save:', e)
        }
    }

    const toggleAgentMode = () => {
        if (agentModeLocked) return
        const next = !agentMode
        setAgentMode(next)
        saveConfig(enabled, next)
    }

    const toggle = (id) => {
        if (agentMode) return
        setEnabled(prev => {
            const next = { ...prev, [id]: !prev[id] }
            saveConfig(next, agentMode)
            return next
        })
        setSaved(false)
    }

    const setAll = (on) => {
        if (agentMode) return
        const next = Object.fromEntries(specialists.map(s => [s.id, on]))
        setEnabled(next)
        saveConfig(next, agentMode)
        setSaved(false)
    }

    const setCategoryAll = (category, on) => {
        if (agentMode) return
        setEnabled(prev => {
            const next = { ...prev }
            for (const s of specialists) {
                if (s.category === category) next[s.id] = on
            }
            saveConfig(next, agentMode)
            return next
        })
        setSaved(false)
    }

    const save = async () => {
        const enabledList = specialists.filter(s => enabled[s.id]).map(s => s.id)
        const availableList = specialists.map(s => s.id)
        try {
            await fetch('/api/pipeline-config', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json', ...authHeaders },
                body: JSON.stringify({
                    agent_mode: agentMode,
                    enabled_specialists: enabledList,
                    available_specialists: availableList,
                }),
            })
            setSaved(true)
            setTimeout(() => setSaved(false), 2000)
            if (onSave) onSave(enabledList)
        } catch (e) {
            console.error('Failed to save:', e)
        }
    }

    const enabledCount = specialists.filter(s => enabled[s.id]).length

    return (
        <div>
            {/* ── Agent mode toggle ── */}
            <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '10px 14px', marginBottom: 12,
                background: agentMode ? 'var(--accent-subtle)' : 'var(--surface)',
                border: `1px solid ${agentMode ? 'var(--accent-border)' : 'var(--border)'}`,
                borderRadius: 'var(--radius)',
                transition: 'all 0.2s',
            }}>
                <div>
                    <span style={{ fontSize: 'var(--fs-base)', fontWeight: 600 }}>
                        {agentMode ? '🤖 Agent Builds Team' : '👤 User Builds Team'}
                    </span>
                    <span style={{ fontSize: 'var(--fs-sm)', color: 'var(--text-dim)', marginLeft: 10 }}>
                        {agentMode
                            ? 'Specialists selected automatically based on contract content'
                            : 'You control which specialists run'}
                    </span>
                    {agentModeLocked && (
                        <span style={{ fontSize: 'var(--fs-sm)', color: 'var(--text-dim)', marginLeft: 10 }}>
                            🔒 set by operator
                        </span>
                    )}
                </div>
                <div
                    onClick={toggleAgentMode}
                    style={{
                        width: 44, height: 24, borderRadius: 12,
                        background: agentMode ? 'var(--accent)' : 'var(--border)',
                        position: 'relative', cursor: agentModeLocked ? 'not-allowed' : 'pointer',
                        transition: 'background 0.2s', flexShrink: 0,
                        opacity: agentModeLocked ? 0.6 : 1,
                    }}
                >
                    <div style={{
                        width: 18, height: 18, borderRadius: 9,
                        background: '#fff', position: 'absolute', top: 3,
                        left: agentMode ? 23 : 3, transition: 'left 0.2s',
                        boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
                    }} />
                </div>
            </div>

            <div style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                marginBottom: 12, flexWrap: 'wrap', gap: 8,
            }}>
                <span style={{ fontSize: 'var(--fs-base)', color: 'var(--text-dim)' }}>
                    {agentMode
                        ? 'Team will be determined at review time'
                        : `${enabledCount}/${specialists.length} specialists enabled`}
                </span>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    {!agentMode && <>
                        <button onClick={() => setAll(true)} style={{ fontSize: 'var(--fs-mono)' }}>Enable All</button>
                        <button onClick={() => setAll(false)} style={{ fontSize: 'var(--fs-mono)' }}>Disable All</button>
                    </>}
                    {saved && <span style={{ fontSize: 'var(--fs-sm)', color: 'var(--green)' }}>✓ Saved</span>}
                    <button className="primary" onClick={save}>Save</button>
                </div>
            </div>

            <div style={{
                padding: '10px 14px', marginBottom: 12,
                background: 'var(--surface)', border: '1px solid var(--border)',
                borderRadius: 'var(--radius)', fontSize: 'var(--fs-mono)', color: 'var(--text-dim)',
            }}>
                {agentMode
                    ? 'The agent will select specialists based on the contract type and content it detects.'
                    : 'Select which specialist agents participate in the contract review pipeline. Disabled specialists won\'t run during analysis. Changes apply to the next review.'}
            </div>

            {CATEGORIES.map(category => {
                const items = specialists.filter(s => s.category === category)
                if (items.length === 0) return null
                const catEnabled = items.filter(s => enabled[s.id]).length
                return (
                    <div key={category} style={{ marginBottom: 16 }}>
                        <div style={{
                            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                            marginBottom: 6, padding: '0 4px',
                        }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                <span style={{ fontSize: 'var(--fs-base)', fontWeight: 600 }}>{category}</span>
                                {!agentMode && (
                                    <span style={{ fontSize: 'var(--fs-sm)', color: 'var(--text-dim)' }}>
                                        {catEnabled}/{items.length}
                                    </span>
                                )}
                            </div>
                            {!agentMode && (
                                <div style={{ display: 'flex', gap: 4 }}>
                                    <button onClick={() => setCategoryAll(category, true)}
                                        style={{ fontSize: 'var(--fs-sm)', padding: '2px 8px', background: 'none', border: '1px solid var(--border)', borderRadius: 4, color: 'var(--text-dim)', cursor: 'pointer' }}>
                                        all on
                                    </button>
                                    <button onClick={() => setCategoryAll(category, false)}
                                        style={{ fontSize: 'var(--fs-sm)', padding: '2px 8px', background: 'none', border: '1px solid var(--border)', borderRadius: 4, color: 'var(--text-dim)', cursor: 'pointer' }}>
                                        all off
                                    </button>
                                </div>
                            )}
                        </div>
                        <div style={{
                            display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
                            gap: 4,
                        }}>
                            {items.map(spec => {
                                const on = !!enabled[spec.id]
                                return (
                                    <div key={spec.id} onClick={() => toggle(spec.id)} style={{
                                        display: 'flex', alignItems: 'center', gap: 10,
                                        padding: '8px 12px',
                                        cursor: agentMode ? 'default' : 'pointer',
                                        background: agentMode ? 'var(--surface)' : on ? 'var(--accent-subtle)' : 'var(--surface)',
                                        border: `1px solid ${!agentMode && on ? 'var(--accent-border)' : 'var(--border)'}`,
                                        borderRadius: 'var(--radius)',
                                        opacity: agentMode ? 0.5 : on ? 1 : 0.6,
                                        transition: 'all 0.15s',
                                    }}>
                                        <div style={{
                                            width: 36, height: 20, borderRadius: 10,
                                            background: !agentMode && on ? 'var(--accent)' : 'var(--border)',
                                            position: 'relative', transition: 'background 0.15s', flexShrink: 0,
                                        }}>
                                            <div style={{
                                                width: 16, height: 16, borderRadius: 8,
                                                background: '#fff', position: 'absolute', top: 2,
                                                left: !agentMode && on ? 18 : 2, transition: 'left 0.15s',
                                            }} />
                                        </div>
                                        <span style={{ fontSize: 'var(--fs-xl)', flexShrink: 0 }}>{spec.emoji}</span>
                                        <div style={{ minWidth: 0 }}>
                                            <div style={{ fontSize: 'var(--fs-base)', fontWeight: 500 }}>{spec.name}</div>
                                            <div style={{ fontSize: 'var(--fs-sm)', color: 'var(--text-dim)' }}>{spec.description}</div>
                                        </div>
                                    </div>
                                )
                            })}
                        </div>
                    </div>
                )
            })}
        </div>
    )
}
