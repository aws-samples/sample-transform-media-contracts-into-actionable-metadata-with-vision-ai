import React, { useState, useEffect } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

function GlossaryPanel({ glossaries }) {
    const [open, setOpen] = useState(null)
    const [expanded, setExpanded] = useState(false)
    const totalTerms = glossaries.reduce((sum, g) => sum + g.termCount, 0)

    return (
        <div style={{
            marginBottom: 12, border: '1px solid var(--border)',
            borderRadius: 'var(--radius)', overflow: 'hidden',
        }}>
            {/* Header row */}
            <div
                onClick={() => setExpanded(e => !e)}
                style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    padding: '8px 14px', cursor: 'pointer',
                    background: 'var(--surface)', userSelect: 'none',
                }}
            >
                <span style={{ fontSize: 'var(--fs-mono)', fontWeight: 600 }}>
                    Glossaries Available
                    <span style={{ fontWeight: 400, color: 'var(--text-dim)', marginLeft: 8 }}>
                        {glossaries.length} glossaries · {totalTerms.toLocaleString()} total terms
                    </span>
                </span>
                <span style={{ fontSize: 'var(--fs-sm)', color: 'var(--text-dim)' }}>{expanded ? '▲' : '▼'}</span>
            </div>

            {expanded && (
                <div style={{ borderTop: '1px solid var(--border)' }}>
                    {glossaries.map((g, i) => (
                        <div key={g.id} style={{ borderBottom: i < glossaries.length - 1 ? '1px solid var(--border)' : 'none' }}>
                            {/* Glossary row */}
                            <div
                                onClick={() => setOpen(open === g.id ? null : g.id)}
                                style={{
                                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                                    padding: '7px 14px', cursor: 'pointer',
                                    background: open === g.id ? 'var(--accent-subtle)' : 'transparent',
                                    transition: 'background 0.1s',
                                }}
                            >
                                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                                    <span style={{ fontSize: 'var(--fs-mono)', fontWeight: 500 }}>{g.name}</span>
                                    <span style={{
                                        fontSize: 'var(--fs-xs)', padding: '1px 7px',
                                        background: 'var(--accent-subtle)', border: '1px solid var(--accent-border)',
                                        borderRadius: 10, color: 'var(--text-dim)',
                                    }}>
                                        {g.termCount.toLocaleString()} terms
                                    </span>
                                </div>
                                <span style={{ fontSize: 'var(--fs-xs)', color: 'var(--text-dim)' }}>{open === g.id ? '▲' : '▼'}</span>
                            </div>

                            {/* Expanded detail */}
                            {open === g.id && (
                                <div style={{
                                    padding: '8px 14px 10px 14px',
                                    background: 'var(--bg)', borderTop: '1px solid var(--border)',
                                }}>
                                    <p style={{ fontSize: 'var(--fs-mono)', color: 'var(--text)', margin: '0 0 6px 0', lineHeight: 1.5 }}>
                                        {g.description}
                                    </p>
                                    {g.source && (
                                        <p style={{ fontSize: 'var(--fs-sm)', color: 'var(--text-dim)', margin: 0 }}>
                                            <span style={{ fontWeight: 600 }}>Source: </span>{g.source}
                                        </p>
                                    )}
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}

const SUGGESTIONS = {
    'FLXKA686AL': [
        "What is Exhibit A Sideletter and how does it affect SVOD residuals?",
        "Explain the difference between synchronization rights and mechanical rights",
        "What is the one-minute threshold rule for podcast downloads?",
        "What does reversion of rights mean and what triggers it?",
        "What is retransmission consent and how does it differ from must-carry?",
        "Explain controlled composition clause",
        "What is an LED volume and how is it used in production?",
    ],
    'LH9EOJ6DBX': [
        "What financial risks were identified across analyzed contracts?",
        "Summarize the residual obligations found in the contracts",
        "What IP ownership issues were flagged by the rights clearance specialist?",
        "Are there any guild compliance concerns in the analyzed contracts?",
        "What are the key payment terms across the contracts?",
    ],
}

export default function KBChat({ accessToken }) {
    const [kbs, setKbs] = useState([])
    const [selectedKb, setSelectedKb] = useState('')
    const [messages, setMessages] = useState([])
    const [input, setInput] = useState('')
    const [loading, setLoading] = useState(false)
    const [glossaries, setGlossaries] = useState([])

    useEffect(() => {
        const headers = accessToken ? { 'Authorization': `Bearer ${accessToken}` } : {}
        fetch('/api/knowledge-bases', { headers })
            .then(r => r.json())
            .then(data => {
                const list = data.knowledgeBases || []
                setKbs(list)
                if (list.length > 0) setSelectedKb(list[0].id)
            })
            .catch(() => {})

        fetch('/api/glossaries', { headers })
            .then(r => r.json())
            .then(data => setGlossaries(data.glossaries || []))
            .catch(() => {})
    }, [accessToken])

    const activeKb = kbs.find(k => k.id === selectedKb)

    const send = async () => {
        const text = input.trim()
        if (!text || !selectedKb) return
        setInput('')
        setMessages(prev => [...prev, { role: 'user', text }])
        setLoading(true)

        try {
            const res = await fetch('/api/kb-query', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...(accessToken && { 'Authorization': `Bearer ${accessToken}` })
                },
                body: JSON.stringify({ knowledgeBaseId: selectedKb, query: text }),
            })
            const data = await res.json()
            if (data.error) {
                setMessages(prev => [...prev, { role: 'assistant', text: `Error: ${data.error}` }])
            } else {
                let reply = data.text
                if (data.citations?.length) {
                    const refs = data.citations.flatMap(c => c.references || []).filter(r => r.location)
                    if (refs.length) {
                        reply += '\n\n---\nSources:\n' + refs.map(r => `• ${r.location}`).join('\n')
                    }
                }
                setMessages(prev => [...prev, { role: 'assistant', text: reply }])
            }
        } catch (e) {
            setMessages(prev => [...prev, { role: 'assistant', text: `Error: ${e.message}` }])
        }
        setLoading(false)
    }

    const clear = () => setMessages([])

    return (
        <div>
            <div style={{
                display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12, flexWrap: 'wrap',
            }}>
                <span style={{ fontSize: 'var(--fs-base)', color: 'var(--text-dim)' }}>Knowledge Base:</span>
                <div style={{ display: 'flex', gap: 4 }}>
                    {kbs.map(kb => (
                        <button
                            key={kb.id}
                            onClick={() => { setSelectedKb(kb.id); clear() }}
                            className={selectedKb === kb.id ? 'tab-active' : ''}
                            style={{ fontSize: 'var(--fs-mono)' }}
                            title={kb.description}
                        >
                            {kb.name}
                        </button>
                    ))}
                </div>
                {activeKb && (
                    <span style={{ fontSize: 'var(--fs-sm)', color: 'var(--text-dim)', fontFamily: 'SF Mono, Menlo, monospace' }}>
                        {activeKb.id}
                    </span>
                )}
                {messages.length > 0 && (
                    <button onClick={clear} style={{ fontSize: 'var(--fs-sm)', marginLeft: 'auto' }}>Clear</button>
                )}
            </div>

            {activeKb && (
                <div style={{
                    padding: '8px 14px', marginBottom: 12,
                    background: 'var(--surface)', border: '1px solid var(--border)',
                    borderRadius: 'var(--radius)', fontSize: 'var(--fs-mono)', color: 'var(--text-dim)',
                }}>
                    {activeKb.description}
                </div>
            )}

            {activeKb?.showGlossaries && glossaries.length > 0 && (
                <GlossaryPanel glossaries={glossaries} />
            )}

            <div className="card" style={{ minHeight: 300, maxHeight: 500, overflowY: 'auto', marginBottom: 12, padding: 12 }}>
                {messages.length === 0 && (
                    <div style={{ color: 'var(--text-dim)', fontSize: 'var(--fs-base)', textAlign: 'center', paddingTop: 60 }}>
                        Ask questions about analyzed contracts or reference materials.
                    </div>
                )}
                {messages.map((m, i) => (
                    <div key={i} className={`chat-message ${m.role}`} style={{ marginBottom: 6 }}>
                        <span style={{ fontSize: 'var(--fs-sm)', color: 'var(--text-dim)' }}>
                            {m.role === 'user' ? 'You' : `KB: ${activeKb?.name || selectedKb}`}
                        </span>
                        <div className="markdown-body" style={{ fontSize: 'var(--fs-base)', marginTop: 2 }}>
                            <Markdown remarkPlugins={[remarkGfm]}>{m.text}</Markdown>
                        </div>
                    </div>
                ))}
                {loading && (
                    <div className="loading-dots"><span /><span /><span /></div>
                )}
            </div>

            <div style={{ display: 'flex', gap: 8 }}>
                <input
                    value={input}
                    onChange={e => setInput(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && send()}
                    placeholder={`Ask ${activeKb?.name || 'the knowledge base'}...`}
                    style={{ flex: 1 }}
                    disabled={!selectedKb}
                />
                <button className="primary" onClick={send} disabled={loading || !selectedKb}>Send</button>
            </div>

            {messages.length === 0 && SUGGESTIONS[selectedKb]?.length > 0 && (
                <div style={{ marginTop: 10 }}>
                    <div style={{ fontSize: 'var(--fs-xs)', color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>Sample questions</div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                    {SUGGESTIONS[selectedKb].map(s => (
                        <button key={s} onClick={() => { setInput(s) }} style={{
                            fontSize: 'var(--fs-sm)', padding: '4px 10px',
                            background: 'var(--surface)',
                            border: '1px solid var(--border)',
                            borderRadius: 12,
                            color: 'var(--text-dim)',
                            cursor: 'pointer',
                            textAlign: 'left',
                            whiteSpace: 'normal',
                            lineHeight: 1.4,
                        }}>
                            {s}
                        </button>
                    ))}
                    </div>
                </div>
            )}
        </div>
    )
}
