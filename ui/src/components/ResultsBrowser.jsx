import React, { useState, useEffect } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Highlight, themes } from 'prism-react-renderer'

const FILE_ICONS = {
    xml: '📋',
    md: '📝',
    json: '⚙️',
    pdf: '📄',
    txt: '📃',
}

const FOLDER_ICONS = {
    pages: '📑',
    specialists: '🧠',
}

const SPECIALIST_LABELS = {
    financial: '💰 Financial Analysis',
    rights_clearance: '⚖️ Rights & Clearance',
    talent_guild_compliance: '🎭 Talent & Guild Compliance',
    regulatory_compliance: '📋 Regulatory Compliance',
    handwriting_analyzer: '✍️ Handwriting Analysis',
    risk_strategist: '🎯 Risk Strategist',
}

function formatTimestamp(ts) {
    if (!ts || ts.length < 15) return ts
    // YYYYMMDDTHHMMSSz → YYYY-MM-DD HH:MM:SS UTC
    const y = ts.slice(0, 4), mo = ts.slice(4, 6), d = ts.slice(6, 8)
    const h = ts.slice(9, 11), mi = ts.slice(11, 13), s = ts.slice(13, 15)
    return `${y}-${mo}-${d} ${h}:${mi}:${s} UTC`
}

function formatBytes(bytes) {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function getFileIcon(name) {
    const ext = name.split('.').pop().toLowerCase()
    return FILE_ICONS[ext] || '📄'
}

function getFileLabel(name) {
    const base = name.replace(/\.[^.]+$/, '').replace(/_/g, ' ')
    // Check specialist labels
    for (const [key, label] of Object.entries(SPECIALIST_LABELS)) {
        if (name.includes(key)) return label
    }
    if (name === 'risk_synthesis.xml') return '🎯 Risk & Negotiation Synthesis'
    if (name === 'final-executive-summary.md') return '📝 Executive Summary'
    if (name === 'timings.json') return '⏱️ Pipeline Timings'
    if (name.startsWith('pages/page_')) {
        const num = name.match(/page_(\d+)/)?.[1]
        return `Page ${parseInt(num)} Extraction`
    }
    return base.charAt(0).toUpperCase() + base.slice(1)
}

function SessionCard({ session, isSelected, onClick }) {
    const contractName = session.name.replace(/_/g, ' ')
    return (
        <div
            onClick={onClick}
            className="card home-card"
            style={{
                cursor: 'pointer',
                borderColor: isSelected ? 'var(--accent-bg)' : undefined,
                background: isSelected ? 'var(--accent-subtle)' : undefined,
                padding: '14px 16px',
                marginBottom: 6,
                display: 'flex',
                alignItems: 'center',
                gap: 12,
            }}
        >
            <div style={{
                width: 40, height: 40, borderRadius: 10,
                background: isSelected ? 'var(--accent-bg)' : 'var(--surface-hover)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 'var(--fs-xl)', flexShrink: 0,
                transition: 'background 0.2s',
            }}>
                📄
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{
                    fontSize: 'var(--fs-base)', fontWeight: 600,
                    whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                }}>
                    {contractName}
                </div>
                <div style={{ fontSize: 'var(--fs-sm)', color: 'var(--text-dim)', marginTop: 2 }}>
                    {formatTimestamp(session.timestamp)}
                </div>
            </div>
            <div style={{ fontSize: 'var(--fs-lg)', color: 'var(--text-dim)', flexShrink: 0 }}>›</div>
        </div>
    )
}

function FileRow({ file, isSelected, onClick }) {
    const label = getFileLabel(file.name)
    const icon = getFileIcon(file.name)
    const isPage = file.name.startsWith('pages/')

    return (
        <div
            onClick={onClick}
            style={{
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                padding: '10px 14px',
                borderRadius: 'var(--radius)',
                background: isSelected ? 'var(--accent-subtle)' : 'transparent',
                borderLeft: isSelected ? '3px solid var(--accent-bg)' : '3px solid transparent',
                transition: 'all 0.15s',
                marginBottom: 2,
            }}
            onMouseEnter={e => { if (!isSelected) e.currentTarget.style.background = 'var(--surface-hover)' }}
            onMouseLeave={e => { if (!isSelected) e.currentTarget.style.background = 'transparent' }}
        >
            <span style={{ fontSize: 'var(--fs-lg)', flexShrink: 0 }}>{icon}</span>
            <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{
                    fontSize: 'var(--fs-mono)', fontWeight: isSelected ? 600 : 400,
                    color: isSelected ? 'var(--accent)' : 'var(--text)',
                }}>
                    {label}
                </div>
                {!isPage && (
                    <div style={{ fontSize: 'var(--fs-xs)', color: 'var(--text-dim)', marginTop: 1 }}>
                        {file.name} · {formatBytes(file.size)}
                    </div>
                )}
            </div>
        </div>
    )
}

function extractXmlTags(content) {
    if (!content) return []
    const matches = [...content.matchAll(/<tag>([^<]+)<\/tag>/g)]
    return matches.map(m => m[1].trim())
}

function ContentViewer({ fileKey, content, metadata }) {
    const ext = fileKey?.split('.').pop().toLowerCase()
    const label = fileKey ? getFileLabel(fileKey.split('/').pop()) : ''
    const filePath = fileKey?.split('/').slice(1).join(' / ')
    const agentsUsed = metadata?.metadataAttributes?.agents_used?.stringListValue || []
    const metaTags = metadata?.metadataAttributes?.tags?.stringListValue || []
    const xmlTags = metaTags.length > 0 ? metaTags : (ext === 'xml' ? extractXmlTags(content) : [])

    if (!content) {
        return (
            <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                height: '100%', color: 'var(--text-dim)', fontSize: 'var(--fs-base)',
            }}>
                Select a file to view its contents
            </div>
        )
    }

    return (
        <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
            {/* Header bar */}
            <div style={{
                padding: '12px 16px',
                borderBottom: '1px solid var(--border)',
                flexShrink: 0,
                display: 'flex',
                flexDirection: 'column',
                gap: 6,
            }}>
                {/* Row 1: title + file path */}
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
                    <div style={{ fontSize: 'var(--fs-md)', fontWeight: 600, whiteSpace: 'nowrap' }}>{label}</div>
                    <div style={{ fontSize: 'var(--fs-sm)', color: 'var(--text-dim)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {filePath}
                    </div>
                </div>

                {/* Row 2: specialists used */}
                {agentsUsed.length > 0 && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                        <span style={{ fontSize: 'var(--fs-xs)', color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>specialists</span>
                        {agentsUsed.map(a => (
                            <span key={a} style={{
                                fontSize: 'var(--fs-xs)', padding: '2px 8px',
                                borderRadius: 12,
                                background: 'var(--accent-subtle)',
                                border: '1px solid var(--accent-border)',
                                color: 'var(--accent)',
                            }}>
                                {a}
                            </span>
                        ))}
                    </div>
                )}

                {/* Row 3: XML tags */}
                {xmlTags.length > 0 && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                        <span style={{ fontSize: 'var(--fs-xs)', color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>tags</span>
                        {xmlTags.map(t => (
                            <span key={t} style={{
                                fontSize: 'var(--fs-xs)', padding: '2px 7px',
                                borderRadius: 4,
                                background: 'rgba(255,255,255,0.05)',
                                border: '1px solid var(--border)',
                                color: 'var(--text-dim)',
                                fontFamily: "'SF Mono', Menlo, monospace",
                            }}>
                                {t}
                            </span>
                        ))}
                    </div>
                )}
            </div>

            {/* Content */}
            <div style={{
                flex: 1, overflow: 'auto', padding: 16,
            }}>
                {ext === 'md' ? (
                    <div className="markdown-body" style={{ fontSize: 'var(--fs-base)', lineHeight: 1.7 }}>
                        <Markdown remarkPlugins={[remarkGfm]}>{content}</Markdown>
                    </div>
                ) : (ext === 'json' || ext === 'xml') ? (
                    <Highlight
                        theme={themes.nightOwl}
                        code={ext === 'json'
                            ? (() => { try { return JSON.stringify(JSON.parse(content), null, 2) } catch { return content } })()
                            : content
                        }
                        language={ext}
                    >
                        {({ className, style, tokens, getLineProps, getTokenProps }) => (
                            <pre className={className} style={{
                                ...style,
                                fontSize: 'var(--fs-mono)', lineHeight: 1.6,
                                fontFamily: "'SF Mono', Menlo, monospace",
                                whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                                background: 'var(--surface, #1e1e1e)',
                                padding: 0, margin: 0,
                            }}>
                                {tokens.map((line, i) => (
                                    <div key={i} {...getLineProps({ line })}>
                                        {line.map((token, key) => (
                                            <span key={key} {...getTokenProps({ token })} />
                                        ))}
                                    </div>
                                ))}
                            </pre>
                        )}
                    </Highlight>
                ) : (
                    <pre style={{
                        fontSize: 'var(--fs-mono)', lineHeight: 1.6,
                        fontFamily: "'SF Mono', Menlo, monospace",
                        whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                    }}>
                        {content}
                    </pre>
                )}
            </div>
        </div>
    )
}

export default function ResultsBrowser({ accessToken }) {
    const [sessions, setSessions] = useState([])
    const [selectedSession, setSelectedSession] = useState(null)
    const [files, setFiles] = useState([])
    const [selectedFile, setSelectedFile] = useState(null)
    const [content, setContent] = useState(null)
    const [metadata, setMetadata] = useState(null)
    const [loading, setLoading] = useState(true)
    const [loadingFile, setLoadingFile] = useState(false)

    // Load sessions
    useEffect(() => {
        setLoading(true)
        const headers = accessToken ? { 'Authorization': `Bearer ${accessToken}` } : {}
        fetch('/api/results', { headers })
            .then(r => r.json())
            .then(data => {
                setSessions(data.sessions || [])
                setLoading(false)
            })
            .catch(() => setLoading(false))
    }, [accessToken])

    // Load files when session selected
    useEffect(() => {
        if (!selectedSession) { setFiles([]); return }
        const headers = accessToken ? { 'Authorization': `Bearer ${accessToken}` } : {}
        fetch(`/api/results/list?prefix=${encodeURIComponent(selectedSession.prefix)}`, { headers })
            .then(r => r.json())
            .then(data => {
                // Group and sort: summary first, then risk, then specialists, then pages, then timings
                const order = { 'summary.md': 0, 'risk_synthesis.xml': 1, 'timings.json': 99 }
                const sorted = (data.files || []).sort((a, b) => {
                    const oa = order[a.name] ?? (a.name.startsWith('specialists/') ? 2 : a.name.startsWith('pages/') ? 3 : 50)
                    const ob = order[b.name] ?? (b.name.startsWith('specialists/') ? 2 : b.name.startsWith('pages/') ? 3 : 50)
                    return oa - ob || a.name.localeCompare(b.name)
                })
                setFiles(sorted)
                setSelectedFile(null)
                setContent(null)
                setMetadata(null)
            })
            .catch(() => {})
    }, [selectedSession, accessToken])

    // Load file content
    const openFile = async (file) => {
        setSelectedFile(file.key)
        setLoadingFile(true)
        setContent(null)
        setMetadata(null)
        try {
            const headers = {
                'Content-Type': 'application/json',
                ...(accessToken ? { 'Authorization': `Bearer ${accessToken}` } : {})
            }
            const [contentRes, metaRes] = await Promise.all([
                fetch('/api/results/fetch', {
                    method: 'POST',
                    headers,
                    body: JSON.stringify({ key: file.key }),
                }).then(r => r.json()),
                fetch('/api/results/metadata', {
                    method: 'POST',
                    headers,
                    body: JSON.stringify({ key: file.key }),
                }).then(r => r.json()),
            ])
            setContent(contentRes.content)
            setMetadata(metaRes)
        } catch { }
        setLoadingFile(false)
    }

    // Group files by folder
    const grouped = {}
    const topLevel = []
    for (const f of files) {
        const slash = f.name.indexOf('/')
        if (slash > 0) {
            const folder = f.name.substring(0, slash)
            if (!grouped[folder]) grouped[folder] = []
            grouped[folder].push(f)
        } else {
            topLevel.push(f)
        }
    }

    return (
        <div>
            {/* Top stats bar */}
            <div style={{
                display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap',
            }}>
                <div className="card" style={{
                    flex: 1, minWidth: 160, padding: '12px 16px',
                    display: 'flex', alignItems: 'center', gap: 10,
                }}>
                    <span style={{ fontSize: 'var(--fs-2xl)' }}>📊</span>
                    <div>
                        <div style={{ fontSize: 'var(--fs-2xl)', fontWeight: 700, color: 'var(--accent)' }}>
                            {sessions.length}
                        </div>
                        <div style={{ fontSize: 'var(--fs-sm)', color: 'var(--text-dim)' }}>Analyses</div>
                    </div>
                </div>
                <div className="card" style={{
                    flex: 1, minWidth: 160, padding: '12px 16px',
                    display: 'flex', alignItems: 'center', gap: 10,
                }}>
                    <span style={{ fontSize: 'var(--fs-2xl)' }}>📁</span>
                    <div>
                        <div style={{ fontSize: 'var(--fs-2xl)', fontWeight: 700, color: 'var(--green)' }}>
                            {files.length}
                        </div>
                        <div style={{ fontSize: 'var(--fs-sm)', color: 'var(--text-dim)' }}>
                            {selectedSession ? 'Files in session' : 'Select a session'}
                        </div>
                    </div>
                </div>
                <div className="card" style={{
                    flex: 2, minWidth: 200, padding: '12px 16px',
                    display: 'flex', alignItems: 'center', gap: 10,
                }}>
                    <span style={{ fontSize: 'var(--fs-2xl)' }}>☁️</span>
                    <div>
                        <div style={{ fontSize: 'var(--fs-base)', fontWeight: 600, color: 'var(--text)' }}>
                            Knowledge Base Bucket
                        </div>
                        <div style={{ fontSize: 'var(--fs-sm)', color: 'var(--text-dim)', fontFamily: "'SF Mono', Menlo, monospace" }}>
                            {import.meta.env.VITE_RESULTS_BUCKET ? `s3://${import.meta.env.VITE_RESULTS_BUCKET}` : 'Knowledge Base Bucket'}
                        </div>
                    </div>
                </div>
            </div>

            {/* Main three-panel layout */}
            <div style={{
                display: 'grid',
                gridTemplateColumns: '280px 220px 1fr',
                gap: 12,
                height: 'calc(100vh - 260px)',
                minHeight: 400,
            }}>
                {/* Panel 1: Sessions */}
                <div className="card" style={{ overflow: 'auto', padding: 10 }}>
                    <div style={{
                        fontSize: 'var(--fs-sm)', fontWeight: 600, color: 'var(--text-dim)',
                        textTransform: 'uppercase', letterSpacing: '0.05em',
                        padding: '4px 6px 10px',
                    }}>
                        Analysis Sessions
                    </div>
                    {loading ? (
                        <div style={{ textAlign: 'center', padding: 40 }}>
                            <div className="loading-dots"><span /><span /><span /></div>
                        </div>
                    ) : sessions.length === 0 ? (
                        <div style={{ color: 'var(--text-dim)', fontSize: 'var(--fs-mono)', textAlign: 'center', padding: 40 }}>
                            No analyses found
                        </div>
                    ) : (
                        sessions.map(s => (
                            <SessionCard
                                key={s.prefix}
                                session={s}
                                isSelected={selectedSession?.prefix === s.prefix}
                                onClick={() => setSelectedSession(s)}
                            />
                        ))
                    )}
                </div>

                {/* Panel 2: File tree */}
                <div className="card" style={{ overflow: 'auto', padding: 10 }}>
                    <div style={{
                        fontSize: 'var(--fs-sm)', fontWeight: 600, color: 'var(--text-dim)',
                        textTransform: 'uppercase', letterSpacing: '0.05em',
                        padding: '4px 6px 10px',
                    }}>
                        Files
                    </div>
                    {!selectedSession ? (
                        <div style={{ color: 'var(--text-dim)', fontSize: 'var(--fs-mono)', textAlign: 'center', padding: 40 }}>
                            ← Select a session
                        </div>
                    ) : (
                        <>
                            {/* Top-level files */}
                            {topLevel.map(f => (
                                <FileRow
                                    key={f.key}
                                    file={f}
                                    isSelected={selectedFile === f.key}
                                    onClick={() => openFile(f)}
                                />
                            ))}
                            {/* Grouped folders */}
                            {Object.entries(grouped).map(([folder, folderFiles]) => (
                                <div key={folder} style={{ marginTop: 8 }}>
                                    <div style={{
                                        fontSize: 'var(--fs-sm)', fontWeight: 600, color: 'var(--text-dim)',
                                        padding: '6px 14px 4px',
                                        display: 'flex', alignItems: 'center', gap: 6,
                                    }}>
                                        <span>{FOLDER_ICONS[folder] || '📁'}</span>
                                        {folder.charAt(0).toUpperCase() + folder.slice(1)}
                                        <span style={{
                                            fontSize: 'var(--fs-xs)', color: 'var(--text-dim)',
                                            background: 'var(--surface-hover)',
                                            padding: '1px 6px', borderRadius: 8,
                                        }}>
                                            {folderFiles.length}
                                        </span>
                                    </div>
                                    {folderFiles.map(f => (
                                        <FileRow
                                            key={f.key}
                                            file={f}
                                            isSelected={selectedFile === f.key}
                                            onClick={() => openFile(f)}
                                        />
                                    ))}
                                </div>
                            ))}
                        </>
                    )}
                </div>

                {/* Panel 3: Content viewer */}
                <div className="card" style={{ overflow: 'hidden', padding: 0 }}>
                    {loadingFile ? (
                        <div style={{
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                            height: '100%', gap: 8,
                        }}>
                            <div className="loading-dots"><span /><span /><span /></div>
                            <span style={{ fontSize: 'var(--fs-mono)', color: 'var(--text-dim)' }}>Loading...</span>
                        </div>
                    ) : (
                        <ContentViewer fileKey={selectedFile} content={content} metadata={metadata} />
                    )}
                </div>
            </div>
        </div>
    )
}
