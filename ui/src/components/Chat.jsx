import React, { useState, useRef, useEffect } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

const SPECIALIST_META = {
    financial: { emoji: '💰', name: 'Financial Analyst' },
    rights_clearance: { emoji: '⚖️', name: 'Rights & Clearance' },
    talent_guild_compliance: { emoji: '🎭', name: 'Talent & Guild' },
    regulatory_compliance: { emoji: '📋', name: 'Regulatory' },
    handwriting_analyzer: { emoji: '✍️', name: 'Handwriting' },
    extractor: { emoji: '🔍', name: 'Extractor' },
    risk_strategist: { emoji: '🎯', name: 'Risk Strategist' },
    summary: { emoji: '📝', name: 'Summary' },
    pdf_convert: { emoji: '📄', name: 'PDF Conversion' },
    page_extraction: { emoji: '🔍', name: 'Page Extraction' },
}

function SpecialistCard({ id, status, detail, elapsed, output }) {
    const meta = SPECIALIST_META[id] || { emoji: '🔧', name: id.replace(/_/g, ' ') }
    const isRunning = status === 'running'
    const isDone = status === 'done'
    const isFailed = status === 'failed'
    const isStandby = status === 'standby'
    const isInactive = status === 'inactive'
    const isQueued = status === 'queued'

    return (
        <div className="card" style={{
            minHeight: 56,
            display: 'flex',
            flexDirection: 'column',
            opacity: isInactive ? 0.25 : 1,
            borderColor: isDone ? 'var(--green-border)' : isRunning ? 'var(--accent)' : isFailed ? 'var(--red)' : isStandby ? 'var(--green-border)' : 'var(--border)',
            borderWidth: isRunning || isDone || isStandby ? 2 : 1,
            background: isRunning ? 'var(--accent-subtle)' : isDone ? 'rgba(0,200,100,0.05)' : 'var(--surface)',
            boxShadow: isRunning ? '0 0 0 1px var(--accent)' : 'none',
            transition: 'all 0.3s',
        }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontSize: 'var(--fs-xl)' }}>{meta.emoji}</span>
                    <span style={{ fontSize: 'var(--fs-base)', fontWeight: 600 }}>{meta.name}</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    {elapsed != null && (
                        <span style={{ fontSize: 'var(--fs-sm)', color: 'var(--text-dim)' }}>{elapsed}s</span>
                    )}
                    {isDone && <span style={{ fontSize: 'var(--fs-md)' }}>✅</span>}
                    {isRunning && (
                        <div className="loading-dots" style={{ transform: 'scale(0.7)' }}>
                            <span /><span /><span />
                        </div>
                    )}
                    {isFailed && <span style={{ fontSize: 'var(--fs-md)' }}>❌</span>}
                    {isStandby && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                            <div className="standby-dot" />
                            <span style={{ fontSize: 'var(--fs-sm)', color: 'var(--green)' }}>standing by</span>
                        </div>
                    )}
                    {isQueued && <span style={{ fontSize: 'var(--fs-sm)', color: 'var(--text-dim)' }}>queued</span>}
                </div>
            </div>
            {detail && (
                <div style={{ fontSize: 'var(--fs-sm)', color: 'var(--text-dim)' }}>{detail}</div>
            )}
        </div>
    )
}

/* ── S3 Picker Modal ── */

function S3Picker({ open, onClose, onSelect, accessToken }) {
    const [bucket, setBucket] = useState('')
    const [prefix, setPrefix] = useState('')
    const [items, setItems] = useState([])
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState('')
    const [history, setHistory] = useState([]) // breadcrumb stack

    useEffect(() => {
        if (open) {
            setBucket('')
            setPrefix('')
            setItems([])
            setHistory([])
            setError('')
            // Load user's testing folder by default
            browse('', '')
        }
    }, [open])

    const browse = async (pfx, bkt) => {
        setLoading(true)
        setError('')
        try {
            const params = new URLSearchParams()
            if (bkt) params.set('bucket', bkt)
            if (pfx) params.set('prefix', pfx)
            const res = await fetch(`/api/s3-browse?${params}`, {
                headers: accessToken ? { 'Authorization': `Bearer ${accessToken}` } : {}
            })
            const ct = res.headers.get('content-type') || ''
            if (!ct.includes('application/json')) {
                const text = await res.text()
                setError(`Server returned non-JSON (${res.status}): ${text.slice(0, 200)}`)
                setItems([])
                setLoading(false)
                return
            }
            const data = await res.json()
            if (data.error) {
                setError(data.error)
                setItems([])
            } else {
                setBucket(data.bucket)
                setPrefix(data.prefix)
                setItems([...data.folders, ...data.files])
            }
        } catch (e) {
            setError(e.message)
        }
        setLoading(false)
    }

    const openFolder = (folderKey) => {
        setHistory(prev => [...prev, prefix])
        browse(folderKey, bucket)
    }

    const goBack = () => {
        const prev = history[history.length - 1] ?? ''
        setHistory(h => h.slice(0, -1))
        browse(prev, bucket)
    }

    const selectFile = (item) => {
        const uri = `s3://${bucket}/${item.key}`
        onSelect(uri)
        onClose()
    }

    const formatSize = (bytes) => {
        if (!bytes) return ''
        if (bytes < 1024) return `${bytes} B`
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
        return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
    }

    if (!open) return null

    return (
        <div style={{
            position: 'fixed', inset: 0, zIndex: 1000,
            background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center',
        }} onClick={onClose}>
            <div style={{
                background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 8,
                width: 520, maxHeight: '70vh', display: 'flex', flexDirection: 'column',
                boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
            }} onClick={e => e.stopPropagation()}>
                {/* Header */}
                <div style={{
                    padding: '12px 16px', borderBottom: '1px solid var(--border)',
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                }}>
                    <div style={{ fontSize: 'var(--fs-md)', fontWeight: 600 }}>📂 Your Uploaded PDFs</div>
                    <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text)', cursor: 'pointer', fontSize: 'var(--fs-lg)' }}>✕</button>
                </div>

                {/* Breadcrumb */}
                <div style={{ padding: '8px 16px', fontSize: 'var(--fs-sm)', color: 'var(--text-dim)', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span style={{ opacity: 0.6 }}>s3://</span>
                    <span style={{ fontWeight: 600 }}>{bucket}</span>
                    {prefix && <span>/ {prefix.replace(/\/$/, '')}</span>}
                    {history.length > 0 && (
                        <button onClick={goBack} style={{ marginLeft: 'auto', fontSize: 'var(--fs-sm)', padding: '2px 8px' }}>← Back</button>
                    )}
                </div>

                {/* Content */}
                <div style={{ flex: 1, overflowY: 'auto', padding: '8px 0' }}>
                    {loading && (
                        <div style={{ padding: 24, textAlign: 'center', color: 'var(--text-dim)', fontSize: 'var(--fs-mono)' }}>
                            <div className="loading-dots"><span /><span /><span /></div>
                            Loading...
                        </div>
                    )}
                    {error && (
                        <div style={{ padding: 16, color: 'var(--red)', fontSize: 'var(--fs-mono)' }}>{error}</div>
                    )}
                    {!loading && !error && items.length === 0 && (
                        <div style={{ padding: 24, textAlign: 'center', color: 'var(--text-dim)', fontSize: 'var(--fs-mono)' }}>No PDFs found at this path.</div>
                    )}
                    {!loading && items.map((item, i) => (
                        <div key={i}
                            onClick={() => item.type === 'folder' ? openFolder(item.key) : selectFile(item)}
                            style={{
                                padding: '8px 16px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 10,
                                fontSize: 'var(--fs-base)', borderBottom: '1px solid var(--border)',
                            }}
                            onMouseEnter={e => e.currentTarget.style.background = 'var(--hover)'}
                            onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                        >
                            <span style={{ fontSize: 'var(--fs-lg)' }}>{item.type === 'folder' ? '📁' : '📄'}</span>
                            <span style={{ flex: 1 }}>{item.name}</span>
                            {item.type === 'file' && (
                                <span style={{ fontSize: 'var(--fs-sm)', color: 'var(--text-dim)' }}>{formatSize(item.size)}</span>
                            )}
                            {item.type === 'folder' && (
                                <span style={{ fontSize: 'var(--fs-sm)', color: 'var(--text-dim)' }}>→</span>
                            )}
                        </div>
                    ))}
                </div>
            </div>
        </div>
    )
}

/* ── Main Chat Component ── */

export default function Chat({ accessToken }) {
    const [messages, setMessages] = useState([])
    const [input, setInput] = useState('')
    const [loading, setLoading] = useState(false)
    const [specialists, setSpecialists] = useState({})
    const [allSpecialists, setAllSpecialists] = useState([])
    const [pipelineStage, setPipelineStage] = useState('')
    const [enabledSpecialists, setEnabledSpecialists] = useState([])
    const [agentMode, setAgentMode] = useState(false)
    const [pickerOpen, setPickerOpen] = useState(false)
    const [uploading, setUploading] = useState(false)
    const fileInputRef = useRef(null)
    const abortRef = useRef(null)

    useEffect(() => {
        const headers = accessToken ? { 'Authorization': `Bearer ${accessToken}` } : {}
        Promise.all([
            fetch('/api/specialists', { headers }).then(r => r.json()),
            fetch('/api/pipeline-config', { headers }).then(r => r.json()),
        ]).then(([specData, configData]) => {
            const all = specData.specialists || []
            const enabled = configData.enabled_specialists || []
            const agentMode = !!configData.agent_mode
            setAllSpecialists(all)
            setEnabledSpecialists(enabled)
            setAgentMode(agentMode)
            const initial = {}
            for (const s of all) {
                initial[s.id] = {
                    status: agentMode || enabled.includes(s.id) ? 'standby' : 'inactive',
                    detail: '', elapsed: null, output: '',
                }
            }
            setSpecialists(initial)
        }).catch(() => {})
    }, [accessToken])

    const isS3Uri = (text) => text.startsWith('s3://')
    const isPdfPath = (text) => text.toLowerCase().endsWith('.pdf')

    const sendChat = async (text) => {
        try {
            const history = messages.filter(m => m.role === 'user' || m.role === 'assistant').slice(-10)
            const res = await fetch('/api/chat', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...(accessToken && { 'Authorization': `Bearer ${accessToken}` })
                },
                body: JSON.stringify({ message: text, history }),
            })
            const data = await res.json()
            if (data.error) {
                setMessages(prev => [...prev, { role: 'assistant', text: `Error: ${data.error}` }])
            } else {
                setMessages(prev => [...prev, { role: 'assistant', text: data.text }])
            }
        } catch (e) {
            setMessages(prev => [...prev, { role: 'assistant', text: `Error: ${e.message}` }])
        }
        setLoading(false)
    }

    const sendAnalyze = async (contractPath) => {
        const initial = {}
        for (const s of allSpecialists) {
            initial[s.id] = {
                status: agentMode || enabledSpecialists.includes(s.id) ? 'queued' : 'inactive',
                detail: '', elapsed: null, output: '',
            }
        }
        setSpecialists(initial)
        setPipelineStage('Starting...')
        setMessages(prev => [...prev, {
            role: 'assistant',
            text: '⚠️ **Analysis in progress** — please stay on this tab until it completes. Navigating away will cancel the pipeline.',
        }])

        if (abortRef.current) abortRef.current.abort()
        const controller = new AbortController()
        abortRef.current = controller

        try {
            const jobId = crypto.randomUUID()
            const res = await fetch('/api/analyze', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...(accessToken && { 'Authorization': `Bearer ${accessToken}` })
                },
                body: JSON.stringify({ contract_path: contractPath, job_id: jobId }),
                signal: controller.signal,
            })

            const reader = res.body.getReader()
            const decoder = new TextDecoder()
            let buffer = ''
            let resultData = null

            while (true) {
                const { done, value } = await reader.read()
                if (done) break
                buffer += decoder.decode(value, { stream: true })
                const lines = buffer.split('\n')
                buffer = lines.pop()

                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue
                    try {
                        const msg = JSON.parse(line.slice(6))
                        if (msg.type === 'session') {
                            const sess = JSON.parse(msg.text)
                            setMessages(prev => [...prev, {
                                role: 'assistant',
                                text: `🔗 **Session:** \`${sess.runtimeSessionId}\``,
                            }])
                        } else if (msg.type === 'progress') {
                            const evt = JSON.parse(msg.text)
                            if (evt.stage && evt.stage !== 'complete') {
                                setSpecialists(prev => ({
                                    ...prev,
                                    [evt.stage]: {
                                        ...prev[evt.stage],
                                        status: evt.status,
                                        detail: evt.detail || '',
                                        elapsed: evt.elapsed,
                                    },
                                }))
                                if (evt.status === 'running') {
                                    setPipelineStage(`Running: ${evt.stage}`)
                                }
                            }
                            if (evt.stage === 'complete') {
                                setPipelineStage('Complete')
                            }
                        } else if (msg.type === 'stdout') {
                            if (msg.text.startsWith('RESULT:')) {
                                try { resultData = JSON.parse(msg.text.slice(7)) } catch {}
                            }
                        } else if (msg.type === 'stderr') {
                            setMessages(prev => [...prev, { role: 'assistant', text: `⚠️ ${msg.text}` }])
                        } else if (msg.type === 'done') {
                            let doneData = {}
                            try { doneData = JSON.parse(msg.text) } catch {}
                            if (doneData.code !== 0) {
                                setMessages(prev => [...prev, {
                                    role: 'assistant',
                                    text: `Analysis failed. Check the orchestrator CloudWatch logs for job \`${doneData.job_id || jobId}\`.`
                                        + (doneData.error ? `\n\nError: ${doneData.error}` : ''),
                                }])
                            } else if (resultData) {
                                setMessages(prev => [...prev, {
                                    role: 'assistant',
                                    text: resultData.summary || 'Analysis complete.',
                                    timings: resultData.timings,
                                }])
                            } else {
                                setMessages(prev => [...prev, { role: 'assistant', text: 'Analysis complete.' }])
                            }
                        }
                    } catch {}
                }
            }
        } catch (e) {
            if (e.name !== 'AbortError') {
                setMessages(prev => [...prev, { role: 'assistant', text: `Error: ${e.message}` }])
            }
        }

        abortRef.current = null
        setLoading(false)
    }

    const send = async () => {
        const text = input.trim()
        if (!text) return

        setInput('')
        setMessages(prev => [...prev, { role: 'user', text }])
        setLoading(true)

        if (isS3Uri(text) || isPdfPath(text)) {
            await sendAnalyze(text)
        } else {
            await sendChat(text)
        }
    }

    const handlePickerSelect = (uri) => {
        setInput(uri)
    }

    const handleFileUpload = async (file) => {
        if (!file || !file.name.toLowerCase().endsWith('.pdf')) return
        setUploading(true)
        try {
            // Get presigned URL
            const urlRes = await fetch('/api/upload-url', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...(accessToken && { 'Authorization': `Bearer ${accessToken}` })
                },
                body: JSON.stringify({ filename: file.name }),
            })
            const { uploadUrl, s3Uri, error } = await urlRes.json()
            if (error) throw new Error(error)

            // Upload directly to S3
            const putRes = await fetch(uploadUrl, {
                method: 'PUT',
                body: file,
                headers: { 'Content-Type': 'application/pdf' },
            })
            if (!putRes.ok) throw new Error(`Upload failed: ${putRes.status}`)

            setInput(s3Uri)
            setMessages(prev => [...prev, {
                role: 'assistant',
                text: `✅ Uploaded **${file.name}** — click Analyze to start the pipeline.`,
            }])
        } catch (e) {
            setMessages(prev => [...prev, { role: 'assistant', text: `Upload error: ${e.message}` }])
        }
        setUploading(false)
    }

    const cancel = () => {
        if (abortRef.current) abortRef.current.abort()
    }

    const specialistIds = allSpecialists.map(s => s.id)

    return (
        <div>
            {/* Messages area */}
            <div className="card" style={{ minHeight: 200, maxHeight: 400, overflowY: 'auto', marginBottom: 12, padding: 12 }}>
                {messages.length === 0 && !loading && (
                    <div style={{ color: 'var(--text-dim)', fontSize: 'var(--fs-base)', textAlign: 'center', paddingTop: 60 }}>
                        Paste an S3 URI, pick a PDF from the bucket, or ask a question.
                    </div>
                )}
                {messages.map((m, i) => (
                    <div key={i} className={`chat-message ${m.role}`} style={{ marginBottom: 6 }}>
                        <span style={{ fontSize: 'var(--fs-sm)', color: 'var(--text-dim)' }}>{m.role === 'user' ? 'You' : 'Analyzer'}</span>
                        {m.role === 'assistant'
                            ? <div className="markdown-body" style={{ fontSize: 'var(--fs-base)', marginTop: 2 }}><Markdown remarkPlugins={[remarkGfm]}>{m.text}</Markdown></div>
                            : <div style={{ fontSize: 'var(--fs-base)', marginTop: 2 }}>{m.text}</div>
                        }
                        {m.timings && (
                            <div style={{ fontSize: 'var(--fs-sm)', color: 'var(--text-dim)', marginTop: 4 }}>
                                {Object.entries(m.timings).map(([k, v]) => `${k}: ${v.toFixed(1)}s`).join(' · ')}
                            </div>
                        )}
                    </div>
                ))}
                {loading && pipelineStage && (
                    <div style={{ fontSize: 'var(--fs-mono)', color: 'var(--accent)', display: 'flex', alignItems: 'center', gap: 8, padding: '8px 0' }}>
                        <div className="loading-dots"><span /><span /><span /></div>
                        {pipelineStage}
                    </div>
                )}
            </div>

            {/* Input bar: upload + S3 picker + input + send */}
            <div style={{ display: 'flex', gap: 8, marginBottom: 16, alignItems: 'center' }}>
                {/* Hidden file input */}
                <input
                    ref={fileInputRef}
                    type="file"
                    accept=".pdf"
                    style={{ display: 'none' }}
                    onChange={e => { handleFileUpload(e.target.files?.[0]); e.target.value = '' }}
                />
                {/* Upload local PDF */}
                <button
                    onClick={() => fileInputRef.current?.click()}
                    disabled={uploading || loading}
                    title="Upload a PDF from your computer"
                    style={{ fontSize: 'var(--fs-xl)', padding: '6px 10px', lineHeight: 1, flexShrink: 0 }}
                >
                    {uploading ? '⏳' : '⬆️'}
                </button>
                {/* Browse S3 */}
                <button onClick={() => setPickerOpen(true)} title="Browse previously uploaded PDFs"
                    style={{ fontSize: 'var(--fs-xl)', padding: '6px 10px', lineHeight: 1, flexShrink: 0 }}>
                    📂
                </button>
                <input
                    value={input}
                    onChange={e => setInput(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && send()}
                    placeholder="s3://bucket/path/to/contract.pdf  or ask a question..."
                    style={{ flex: 1 }}
                />
                {loading
                    ? <button className="danger" onClick={cancel}>Cancel</button>
                    : <button className="primary" onClick={send}>Analyze</button>
                }
            </div>

            {/* S3 Picker Modal */}
            <S3Picker open={pickerOpen} onClose={() => setPickerOpen(false)} onSelect={handlePickerSelect} accessToken={accessToken} />

            {/* Specialist cards */}
            {specialistIds.length > 0 && (
                <>
                <div style={{ fontSize: 'var(--fs-base)', fontWeight: 600, color: 'var(--text-dim)', marginBottom: 8, letterSpacing: '0.03em' }}>
                    Specialist Agents
                </div>
                <div style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
                    gap: 8,
                }}>
                    {specialistIds.map(id => (
                        <SpecialistCard
                            key={id}
                            id={id}
                            status={specialists[id]?.status}
                            detail={specialists[id]?.detail}
                            elapsed={specialists[id]?.elapsed}
                            output={specialists[id]?.output}
                        />
                    ))}
                </div>
                </>
            )}
        </div>
    )
}
