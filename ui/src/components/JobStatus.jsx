import { useState, useEffect, useRef } from 'react'

const STATUS_CONFIG = {
    COMPLETE: { color: 'var(--green)', bg: 'var(--green-subtle)', border: 'var(--green-border)', label: 'Complete', dot: true },
    RUNNING:  { color: 'var(--yellow)', bg: 'var(--thinking-bg)', border: 'var(--thinking-border)', label: 'Running', dot: true, pulse: true },
    FAILED:   { color: 'var(--red)', bg: 'rgba(248,81,73,0.08)', border: 'rgba(248,81,73,0.25)', label: 'Failed', dot: true },
    PENDING:  { color: 'var(--text-dim)', bg: 'transparent', border: 'var(--border)', label: 'Pending', dot: false },
}

const SPECIALIST_LABELS = {
    financial:               '💰 Financial',
    rights_clearance:        '⚖️ Rights',
    talent_guild_compliance: '🎭 Talent',
    regulatory_compliance:   '📋 Regulatory',
    risk_strategist:         '🎯 Risk',
    handwriting_analyzer:    '✍️ Handwriting',
    orchestrator:            '🎼 Orchestrator',
}

function StatusBadge({ status }) {
    const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.PENDING
    return (
        <span style={{
            display: 'inline-flex', alignItems: 'center', gap: 5,
            fontSize: 'var(--fs-xs)', fontWeight: 600,
            padding: '2px 8px', borderRadius: 10,
            background: cfg.bg, border: `1px solid ${cfg.border}`, color: cfg.color,
            textTransform: 'uppercase', letterSpacing: '0.04em',
        }}>
            {cfg.dot && (
                <span style={{
                    width: 6, height: 6, borderRadius: '50%', background: cfg.color, flexShrink: 0,
                    ...(cfg.pulse ? { animation: 'standby-blink 1.4s ease-in-out infinite' } : {}),
                }} />
            )}
            {cfg.label}
        </span>
    )
}

function elapsed(started, completed) {
    if (!started || !completed) return null
    const s = Math.round((new Date(completed) - new Date(started)) / 1000)
    if (s < 60) return `${s}s`
    return `${Math.floor(s / 60)}m ${s % 60}s`
}

function contractName(job) {
    const key = job.orchestrator?.result_s3_key || job.specialists?.[0]?.result_s3_key || ''
    if (!key) return job.job_id.slice(0, 8) + '…'
    // key format: jobs-canonical-versions/{uuid}-{nn}_{Contract_Name}_{YYYYMMDDTHHMMSSz}/...
    // or:         {uuid}-{nn}_{Contract_Name}_{YYYYMMDDTHHMMSSz}/...
    // Strip known prefixes
    const stripped = key.replace(/^jobs-canonical-versions\//, '').replace(/^jobs-kb-versions\//, '')
    const prefix = stripped.split('/')[0]
    // Strip trailing timestamp (_YYYYMMDDTHHMMSSz)
    const lastUnderscore = prefix.lastIndexOf('_')
    const withoutTimestamp = lastUnderscore > 0 ? prefix.slice(0, lastUnderscore) : prefix
    // Strip leading UUID prefix (xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx-NN_)
    const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?:-\d+)?_/i
    const name = withoutTimestamp.replace(uuidPattern, '')
    return name ? name.replace(/_/g, ' ') : withoutTimestamp.replace(/_/g, ' ')
}

function jobTimestamp(job) {
    const ts = job.orchestrator?.started_at
    if (!ts) return ''
    return new Date(ts).toLocaleString(undefined, {
        month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit',
    })
}

function overallStatus(job) {
    const orch = job.orchestrator?.status
    if (orch) return orch
    const statuses = job.specialists.map(s => s.status)
    if (statuses.some(s => s === 'FAILED')) return 'FAILED'
    if (statuses.some(s => s === 'RUNNING')) return 'RUNNING'
    if (statuses.every(s => s === 'COMPLETE')) return 'COMPLETE'
    return 'PENDING'
}

function resultPrefix(job) {
    const key = job.orchestrator?.result_s3_key || job.specialists?.[0]?.result_s3_key || ''
    if (!key) return null
    return key.split('/').slice(0, -1).join('/') + '/'
}

export default function JobStatus({ onNavigateToResults, accessToken }) {
    const [jobs, setJobs] = useState([])
    const [loading, setLoading] = useState(true)
    const [selected, setSelected] = useState(null)
    const [autoRefresh, setAutoRefresh] = useState(true)
    const [jobIdSearch, setJobIdSearch] = useState('')
    const [statusFilter, setStatusFilter] = useState('ALL')
    const intervalRef = useRef(null)
    const searchRef = useRef(null)

    async function fetchJobs(search = jobIdSearch, status = statusFilter) {
        setLoading(true)
        try {
            const params = new URLSearchParams()
            if (search) params.set('job_id', search)
            if (status !== 'ALL') params.set('status', status)
            const headers = accessToken ? { 'Authorization': `Bearer ${accessToken}` } : {}
            const res = await fetch(`/api/jobs?${params}`, { headers })
            const data = await res.json()
            setJobs(data.jobs || [])
        } catch { }
        setLoading(false)
    }

    useEffect(() => {
        fetchJobs()
    }, [])

    useEffect(() => {
        if (autoRefresh && !jobIdSearch) {
            intervalRef.current = setInterval(() => fetchJobs(), 5000)
        } else {
            clearInterval(intervalRef.current)
        }
        return () => clearInterval(intervalRef.current)
    }, [autoRefresh, jobIdSearch, statusFilter])

    function handleSearch(e) {
        e.preventDefault()
        fetchJobs(jobIdSearch, statusFilter)
    }

    function handleStatusChange(s) {
        setStatusFilter(s)
        setSelected(null)
        fetchJobs(jobIdSearch, s)
    }

    function handleSearchInput(val) {
        setJobIdSearch(val)
        if (!val) fetchJobs('', statusFilter)
    }

    const selectedJob = jobs.find(j => j.job_id === selected)

    async function handleDeleteJob(jobId) {
        if (!confirm(`Delete job ${jobId.slice(0, 8)}…? This removes all records from DynamoDB.`)) return
        try {
            const headers = accessToken ? { 'Authorization': `Bearer ${accessToken}` } : {}
            const res = await fetch(`/api/jobs/${jobId}`, { method: 'DELETE', headers })
            if (!res.ok) throw new Error((await res.json()).error || res.statusText)
            setSelected(null)
            fetchJobs()
        } catch (e) {
            alert(`Delete failed: ${e.message}`)
        }
    }

    const counts = {
        RUNNING: jobs.filter(j => overallStatus(j) === 'RUNNING').length,
        COMPLETE: jobs.filter(j => overallStatus(j) === 'COMPLETE').length,
        FAILED: jobs.filter(j => overallStatus(j) === 'FAILED').length,
    }

    return (
        <div>
            {/* Stats bar */}
            <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap' }}>
                {[
                    { label: 'Running', count: counts.RUNNING, color: 'var(--yellow)', bg: 'var(--thinking-bg)', border: 'var(--thinking-border)', pulse: true },
                    { label: 'Complete', count: counts.COMPLETE, color: 'var(--green)', bg: 'var(--green-subtle)', border: 'var(--green-border)' },
                    { label: 'Failed', count: counts.FAILED, color: 'var(--red)', bg: 'rgba(248,81,73,0.08)', border: 'rgba(248,81,73,0.2)' },
                    { label: 'Total', count: jobs.length, color: 'var(--accent)', bg: 'var(--accent-subtle)', border: 'var(--accent-border)' },
                ].map(({ label, count, color, bg, border, pulse }) => (
                    <div key={label} className="card" style={{
                        flex: 1, minWidth: 120, padding: '10px 14px',
                        display: 'flex', alignItems: 'center', gap: 10,
                        background: bg, borderColor: border,
                    }}>
                        <div style={{
                            width: 8, height: 8, borderRadius: '50%', background: color, flexShrink: 0,
                            ...(pulse && count > 0 ? { animation: 'standby-blink 1.4s ease-in-out infinite' } : {}),
                        }} />
                        <div>
                            <div style={{ fontSize: 'var(--fs-2xl)', fontWeight: 700, color, lineHeight: 1 }}>{count}</div>
                            <div style={{ fontSize: 'var(--fs-xs)', color: 'var(--text-dim)', marginTop: 2 }}>{label}</div>
                        </div>
                    </div>
                ))}

                <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
                    <button
                        onClick={() => fetchJobs()}
                        style={{ fontSize: 'var(--fs-sm)', padding: '5px 12px' }}
                    >
                        ↻ Refresh
                    </button>
                    <button
                        onClick={() => setAutoRefresh(v => !v)}
                        style={{
                            fontSize: 'var(--fs-sm)', padding: '5px 12px',
                            background: autoRefresh ? 'var(--accent-subtle)' : undefined,
                            borderColor: autoRefresh ? 'var(--accent-border)' : undefined,
                            color: autoRefresh ? 'var(--accent)' : undefined,
                        }}
                    >
                        {autoRefresh ? '⏸ Auto' : '▶ Auto'}
                    </button>
                </div>
            </div>

            {/* Search + filter bar */}
            <div style={{ display: 'flex', gap: 8, marginBottom: 14, alignItems: 'center', flexWrap: 'wrap' }}>
                <form onSubmit={handleSearch} style={{ display: 'flex', gap: 6, flex: 1, minWidth: 200 }}>
                    <input
                        ref={searchRef}
                        value={jobIdSearch}
                        onChange={e => handleSearchInput(e.target.value)}
                        placeholder="Search by job ID…"
                        style={{ flex: 1, fontSize: 'var(--fs-sm)', padding: '5px 10px' }}
                    />
                    <button type="submit" style={{ fontSize: 'var(--fs-sm)', padding: '5px 12px', flexShrink: 0 }}>
                        Search
                    </button>
                    {jobIdSearch && (
                        <button
                            type="button"
                            onClick={() => { setJobIdSearch(''); fetchJobs('', statusFilter) }}
                            style={{ fontSize: 'var(--fs-sm)', padding: '5px 10px', flexShrink: 0 }}
                        >
                            ✕
                        </button>
                    )}
                </form>

                <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
                    {['ALL', 'RUNNING', 'COMPLETE', 'FAILED', 'PENDING'].map(s => {
                        const cfg = s === 'ALL'
                            ? { color: 'var(--accent)', bg: 'var(--accent-subtle)', border: 'var(--accent-border)' }
                            : STATUS_CONFIG[s] || STATUS_CONFIG.PENDING
                        const active = statusFilter === s
                        return (
                            <button
                                key={s}
                                onClick={() => handleStatusChange(s)}
                                style={{
                                    fontSize: 'var(--fs-xs)', padding: '4px 10px',
                                    background: active ? cfg.bg : 'var(--surface)',
                                    borderColor: active ? cfg.border : 'var(--border)',
                                    color: active ? cfg.color : 'var(--text-dim)',
                                    fontWeight: active ? 600 : 400,
                                }}
                            >
                                {s}
                            </button>
                        )
                    })}
                </div>
            </div>

            {/* Two-panel layout */}
            <div style={{
                display: 'grid',
                gridTemplateColumns: '340px 1fr',
                gap: 12,
                height: 'calc(100vh - 280px)',
                minHeight: 400,
            }}>
                {/* Job list */}
                <div className="card" style={{ overflow: 'auto', padding: 10 }}>
                    <div style={{
                        fontSize: 'var(--fs-sm)', fontWeight: 600, color: 'var(--text-dim)',
                        textTransform: 'uppercase', letterSpacing: '0.05em',
                        padding: '4px 6px 10px',
                    }}>
                        Jobs
                    </div>

                    {loading ? (
                        <div style={{ textAlign: 'center', padding: 40 }}>
                            <div className="loading-dots"><span /><span /><span /></div>
                        </div>
                    ) : jobs.length === 0 ? (
                        <div style={{ color: 'var(--text-dim)', fontSize: 'var(--fs-mono)', textAlign: 'center', padding: 40 }}>
                            No jobs found
                        </div>
                    ) : (
                        jobs.map(job => {
                            const status = overallStatus(job)
                            const isSelected = selected === job.job_id
                            const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.PENDING
                            return (
                                <div
                                    key={job.job_id}
                                    onClick={() => setSelected(isSelected ? null : job.job_id)}
                                    className="home-card"
                                    style={{
                                        cursor: 'pointer',
                                        padding: '10px 12px',
                                        marginBottom: 4,
                                        borderRadius: 'var(--radius)',
                                        border: `1px solid ${isSelected ? cfg.border : 'var(--border)'}`,
                                        background: isSelected ? cfg.bg : 'var(--surface)',
                                        borderLeft: `3px solid ${cfg.color}`,
                                    }}
                                >
                                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                                        <div style={{
                                            fontSize: 'var(--fs-base)', fontWeight: 600,
                                            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                                        }}>
                                            {contractName(job)}
                                        </div>
                                        <StatusBadge status={status} />
                                    </div>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 5 }}>
                                        <span style={{ fontSize: 'var(--fs-xs)', color: 'var(--text-dim)', fontFamily: "'SF Mono', Menlo, monospace" }}>
                                            {job.job_id.slice(0, 8)}…
                                        </span>
                                        <span style={{ fontSize: 'var(--fs-xs)', color: 'var(--text-dim)' }}>
                                            {jobTimestamp(job)}
                                        </span>
                                        {job.orchestrator?.started_at && (
                                            <span style={{ fontSize: 'var(--fs-xs)', color: 'var(--text-dim)', marginLeft: 'auto' }}>
                                                {elapsed(job.orchestrator.started_at, job.orchestrator.completed_at)}
                                            </span>
                                        )}
                                    </div>
                                </div>
                            )
                        })
                    )}
                </div>

                {/* Job detail */}
                <div className="card" style={{ overflow: 'auto', padding: 20 }}>
                    {!selectedJob ? (
                        <div style={{
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                            height: '100%', color: 'var(--text-dim)', fontSize: 'var(--fs-base)',
                        }}>
                            ← Select a job to see details
                        </div>
                    ) : (
                        <JobDetail
                            job={selectedJob}
                            onViewResults={onNavigateToResults ? () => {
                                const prefix = resultPrefix(selectedJob)
                                if (prefix) onNavigateToResults(prefix)
                            } : null}
                            onDelete={() => handleDeleteJob(selectedJob.job_id)}
                        />
                    )}
                </div>
            </div>
        </div>
    )
}

function JobDetail({ job, onViewResults, onDelete }) {
    const status = overallStatus(job)
    const name = contractName(job)
    const orch = job.orchestrator

    const allRows = [
        ...(orch ? [{ ...orch, specialist: 'orchestrator' }] : []),
        ...job.specialists.sort((a, b) => (a.specialist || '').localeCompare(b.specialist || '')),
    ]

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
            {/* Header */}
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
                <div>
                    <div style={{ fontSize: 'var(--fs-lg)', fontWeight: 700, marginBottom: 4 }}>{name}</div>
                    <div style={{ fontSize: 'var(--fs-mono)', color: 'var(--text-dim)', fontFamily: "'SF Mono', Menlo, monospace" }}>
                        {job.job_id}
                    </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
                    <StatusBadge status={status} />
                    {onViewResults && status === 'COMPLETE' && (
                        <button
                            onClick={onViewResults}
                            className="primary"
                            style={{ fontSize: 'var(--fs-sm)', padding: '5px 12px' }}
                        >
                            View Results →
                        </button>
                    )}
                    {onDelete && (
                        <button
                            onClick={onDelete}
                            style={{
                                fontSize: 'var(--fs-sm)', padding: '5px 12px',
                                color: 'var(--red)', borderColor: 'rgba(248,81,73,0.3)',
                                background: 'rgba(248,81,73,0.06)',
                            }}
                        >
                            Delete
                        </button>
                    )}
                </div>
            </div>

            {/* Timing summary */}
            {orch && (
                <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                    {[
                        { label: 'Created', value: orch.started_at ? new Date(orch.started_at).toLocaleString() : '—' },
                        { label: 'Duration', value: elapsed(orch.started_at, orch.completed_at) || (orch.completed_at ? '—' : 'running…') },
                    ].map(({ label, value }) => (
                        <div key={label} style={{
                            background: 'var(--surface-hover)', borderRadius: 6,
                            padding: '8px 14px', minWidth: 140,
                        }}>
                            <div style={{ fontSize: 'var(--fs-xs)', color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 3 }}>
                                {label}
                            </div>
                            <div style={{ fontSize: 'var(--fs-mono)', fontFamily: "'SF Mono', Menlo, monospace" }}>{value}</div>
                        </div>
                    ))}
                </div>
            )}

            {/* Specialist breakdown */}
            <div>
                <div style={{
                    fontSize: 'var(--fs-sm)', fontWeight: 600, color: 'var(--text-dim)',
                    textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 10,
                }}>
                    Specialist Breakdown
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {allRows.map(row => {
                        const cfg = STATUS_CONFIG[row.status] || STATUS_CONFIG.PENDING
                        const label = SPECIALIST_LABELS[row.specialist] || row.specialist
                        const dur = elapsed(row.started_at, row.completed_at)
                        return (
                            <div key={row.specialist} style={{
                                display: 'flex', alignItems: 'center', gap: 12,
                                padding: '8px 12px', borderRadius: 6,
                                background: 'var(--surface-hover)',
                                borderLeft: `3px solid ${cfg.color}`,
                            }}>
                                <div style={{ flex: 1, fontSize: 'var(--fs-base)', fontWeight: 500 }}>{label}</div>
                                <StatusBadge status={row.status} />
                                {dur && (
                                    <div style={{ fontSize: 'var(--fs-xs)', color: 'var(--text-dim)', fontFamily: "'SF Mono', Menlo, monospace", minWidth: 36, textAlign: 'right' }}>
                                        {dur}
                                    </div>
                                )}
                                {row.error && (
                                    <div style={{
                                        fontSize: 'var(--fs-xs)', color: 'var(--red)',
                                        maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                                    }}>
                                        {row.error}
                                    </div>
                                )}
                            </div>
                        )
                    })}
                </div>
            </div>

            {/* S3 output key */}
            {orch?.result_s3_key && (
                <div>
                    <div style={{
                        fontSize: 'var(--fs-sm)', fontWeight: 600, color: 'var(--text-dim)',
                        textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6,
                    }}>
                        Output
                    </div>
                    <div style={{
                        fontSize: 'var(--fs-mono)', fontFamily: "'SF Mono', Menlo, monospace",
                        color: 'var(--text-dim)', background: 'var(--surface-hover)',
                        padding: '6px 10px', borderRadius: 6, wordBreak: 'break-all',
                    }}>
                        {orch.result_s3_key}
                    </div>
                </div>
            )}
        </div>
    )
}
