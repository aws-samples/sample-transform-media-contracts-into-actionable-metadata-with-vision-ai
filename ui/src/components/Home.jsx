import React from 'react'

export default function Home({ onNavigate, branding = {} }) {
    const tabs = [
        ['team', '⚖️ Legal Team Builder', 'Select which specialist agents to include in the review'],
        ['chat', '💬 Chat', 'Send contracts to the analysis pipeline and view results'],
        ['jobs', '📋 Jobs', 'Monitor running and completed pipeline jobs across all users'],
        ['results', '📊 Results', 'Browse past analysis sessions stored in S3'],
        ['kb', '📚 KB Chat', 'Query analyzed contracts and reference materials via knowledge base'],
    ]

    return (
        <div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 8 }}>
                {tabs.map(([key, name, desc]) => (
                    <div key={key} className="card home-card" style={{ padding: 12, cursor: 'pointer' }}
                        onClick={() => onNavigate?.(key)}>
                        <div style={{ fontSize: 'var(--fs-md)', fontWeight: 500, marginBottom: 4 }}>{name}</div>
                        <div style={{ fontSize: 'var(--fs-mono)', color: 'var(--text-dim)' }}>{desc}</div>
                    </div>
                ))}
            </div>
        </div>
    )
}
