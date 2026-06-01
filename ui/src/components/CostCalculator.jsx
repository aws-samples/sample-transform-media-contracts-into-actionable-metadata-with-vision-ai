import { useState, useEffect } from 'react'

const fmt = (n, decimals = 6) => n === 0 ? '$0.000000' : `$${n.toFixed(decimals)}`
const fmtTotal = (n) => `$${n.toFixed(4)}`

export default function CostCalculator({ accessToken }) {
    const [pricing, setPricing] = useState(null)
    const [agents, setAgents] = useState([])
    const [contracts, setContracts] = useState(100)
    const [pagesPerContract, setPagesPerContract] = useState(5)

    useEffect(() => {
        const headers = accessToken ? { 'Authorization': `Bearer ${accessToken}` } : {}
        fetch('/api/pricing', { headers })
            .then(r => r.json())
            .then(data => {
                setPricing(data)
                setAgents(data.agents.map(a => ({
                    ...a,
                    include: a.default_include,
                    model: a.default_model,
                })))
            })
            .catch(() => {})
    }, [accessToken])

    function toggleInclude(id) {
        setAgents(prev => prev.map(a => a.id === id ? { ...a, include: !a.include } : a))
    }

    function setModel(id, model) {
        setAgents(prev => prev.map(a => a.id === id ? { ...a, model } : a))
    }

    if (!pricing) {
        return (
            <div style={{ display: 'flex', justifyContent: 'center', padding: 40 }}>
                <div className="loading-dots"><span /><span /><span /></div>
            </div>
        )
    }

    const { document_constants: dc, models } = pricing
    const tokensPerPage = dc.avg_tokens_per_page

    function calcAgent(agent) {
        const m = models.find(m => m.name === agent.model)
        if (!m) return null
        const inputPerTok = m.input_per_1m / 1_000_000
        const outputPerTok = m.output_per_1m / 1_000_000

        // Total input tokens = prompt + page tokens + (image tokens if applicable)
        const imageTokensPerPage = agent.uses_images ? dc.avg_image_tokens : 0
        const totalInputPerPage = agent.prompt_tokens + tokensPerPage + imageTokensPerPage

        const inputCostPerPage = totalInputPerPage * inputPerTok
        const outputCostPerPage = agent.max_output_tokens * outputPerTok

        const inputCostPerDoc = inputCostPerPage * pagesPerContract
        const outputCostPerDoc = outputCostPerPage * pagesPerContract

        return {
            inputPerPage: inputCostPerPage,
            outputPerPage: outputCostPerPage,
            totalPerPage: inputCostPerPage + outputCostPerPage,
            inputPerDoc: inputCostPerDoc,
            outputPerDoc: outputCostPerDoc,
            totalPerDoc: inputCostPerDoc + outputCostPerDoc,
        }
    }

    const rows = agents.map(a => ({ ...a, costs: calcAgent(a) }))
    const selected = rows.filter(r => r.include)
    const totalPerPage = selected.reduce((s, r) => s + (r.costs?.totalPerPage ?? 0), 0)
    const totalPerDoc = selected.reduce((s, r) => s + (r.costs?.totalPerDoc ?? 0), 0)
    const totalAllContracts = totalPerDoc * contracts

    const colStyle = { padding: '8px 10px', fontSize: 'var(--fs-mono)', textAlign: 'right', borderBottom: '1px solid var(--border)' }
    const colStyleLeft = { ...colStyle, textAlign: 'left' }
    const headerStyle = { ...colStyle, color: 'var(--text-dim)', fontWeight: 600, fontSize: 'var(--fs-sm)', borderBottom: '1px solid var(--border)', background: 'var(--table-header-bg)' }
    const headerStyleLeft = { ...headerStyle, textAlign: 'left' }

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

            {/* Global inputs */}
            <div className="card" style={{ display: 'flex', gap: 24, alignItems: 'center', flexWrap: 'wrap' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <label style={{ fontSize: 'var(--fs-sm)', color: 'var(--text-dim)', whiteSpace: 'nowrap' }}>Contracts to process</label>
                    <input type="number" min={1} value={contracts}
                        onChange={e => setContracts(Math.max(1, parseInt(e.target.value) || 1))}
                        style={{ width: 90 }} />
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <label style={{ fontSize: 'var(--fs-sm)', color: 'var(--text-dim)', whiteSpace: 'nowrap' }}>Pages per contract</label>
                    <input type="number" min={1} value={pagesPerContract}
                        onChange={e => setPagesPerContract(Math.max(1, parseInt(e.target.value) || 1))}
                        style={{ width: 70 }} />
                </div>
                <div style={{ marginLeft: 'auto', fontSize: 'var(--fs-sm)', color: 'var(--text-dim)' }}>
                    {selected.length} agent{selected.length !== 1 ? 's' : ''} selected
                </div>
            </div>

            {/* Agent table */}
            <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
                <div style={{ overflowX: 'auto' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                        <thead>
                            <tr>
                                <th style={{ ...headerStyleLeft, width: 40 }}>On</th>
                                <th style={headerStyleLeft}>Agent</th>
                                <th style={headerStyleLeft}>Model</th>
                                <th style={headerStyle}>Input $/page</th>
                                <th style={headerStyle}>Output $/page</th>
                                <th style={headerStyle}>Total $/page</th>
                                <th style={headerStyle}>Total $/doc</th>
                            </tr>
                        </thead>
                        <tbody>
                            {rows.map(row => {
                                const c = row.costs
                                const dim = !row.include
                                const cellStyle = { ...colStyle, opacity: dim ? 0.35 : 1 }
                                const cellStyleLeft = { ...colStyleLeft, opacity: dim ? 0.35 : 1 }
                                return (
                                    <tr key={row.id} style={{ background: row.include ? 'transparent' : 'rgba(0,0,0,0.1)' }}>
                                        <td style={{ ...colStyleLeft, width: 40 }}>
                                            <input type="checkbox" checked={row.include}
                                                onChange={() => toggleInclude(row.id)} />
                                        </td>
                                        <td style={cellStyleLeft}>
                                            <span style={{ fontWeight: 500 }}>{row.label}</span>
                                            {row.uses_images && (
                                                <span style={{ marginLeft: 6, fontSize: 'var(--fs-xs)', color: 'var(--accent)', opacity: 0.7 }}>🖼 vision</span>
                                            )}
                                        </td>
                                        <td style={{ ...colStyleLeft, opacity: dim ? 0.35 : 1 }}>
                                            <select value={row.model} onChange={e => setModel(row.id, e.target.value)}
                                                style={{ width: 'auto', fontSize: 'var(--fs-sm)', padding: '3px 6px' }}>
                                                {models.map(m => (
                                                    <option key={m.name} value={m.name}>{m.name}</option>
                                                ))}
                                            </select>
                                        </td>
                                        <td style={cellStyle}>{c ? fmt(c.inputPerPage) : '—'}</td>
                                        <td style={cellStyle}>{c ? fmt(c.outputPerPage) : '—'}</td>
                                        <td style={{ ...cellStyle, color: row.include ? 'var(--accent)' : undefined }}>{c ? fmt(c.totalPerPage) : '—'}</td>
                                        <td style={cellStyle}>{c ? fmt(c.totalPerDoc, 4) : '—'}</td>
                                    </tr>
                                )
                            })}
                        </tbody>
                        <tfoot>
                            <tr style={{ borderTop: '2px solid var(--border)' }}>
                                <td colSpan={3} style={{ ...colStyleLeft, fontWeight: 600, color: 'var(--text-dim)', fontSize: 'var(--fs-sm)' }}>
                                    SELECTED TOTALS
                                </td>
                                <td style={{ ...colStyle, fontWeight: 600 }}></td>
                                <td style={{ ...colStyle, fontWeight: 600 }}></td>
                                <td style={{ ...colStyle, fontWeight: 600, color: 'var(--accent)' }}>{fmt(totalPerPage)}</td>
                                <td style={{ ...colStyle, fontWeight: 600 }}>{fmt(totalPerDoc, 4)}</td>
                            </tr>
                        </tfoot>
                    </table>
                </div>
            </div>

            {/* Summary */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 8 }}>
                {[
                    ['Total $/page', fmt(totalPerPage)],
                    ['Total $/contract', fmtTotal(totalPerDoc)],
                    [`Total for ${contracts.toLocaleString()} contracts`, fmtTotal(totalAllContracts)],
                ].map(([label, value]) => (
                    <div key={label} className="card" style={{ textAlign: 'center' }}>
                        <div style={{ fontSize: 'var(--fs-sm)', color: 'var(--text-dim)', marginBottom: 4 }}>{label}</div>
                        <div style={{ fontSize: 'var(--fs-xl)', fontWeight: 600, color: 'var(--green)' }}>{value}</div>
                    </div>
                ))}
            </div>

            <div style={{ fontSize: 'var(--fs-xs)', color: 'var(--text-dim)' }}>
                Estimates based on max output tokens. Actual costs will be lower. Prices from <code style={{ fontSize: 'var(--fs-xs)' }}>config/pricing.json</code>.
            </div>
        </div>
    )
}
