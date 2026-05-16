import React, { useState } from 'react';

function ChatMessage({ message, onFollowUp }) {
  const isUser = message.role === 'user';
  const [showDrilldown, setShowDrilldown] = useState(false);
  const explain = message.meta?.query_explain;
  const drilldown = message.meta?.drilldown;
  const suggestions = message.meta?.follow_up_suggestions || [];

  const drillColumns = drilldown?.columns || [];
  const drillRows = drilldown?.rows || [];

  return (
    <div className={`chat-message ${isUser ? 'chat-message--user' : 'chat-message--assistant'}`}>
      {/* Avatar */}
      <div className="chat-avatar">
        {isUser ? '👤' : '🤖'}
      </div>

      {/* Bubble */}
      <div className="chat-bubble-wrapper">
        <div className="chat-bubble">
          <p className="chat-text">{message.content}</p>

          {/* Action Badge (for agentic operations) */}
          {message.action && (
            <div className="chat-action-badge">
              <span>⚡</span>
              <span>
                Action: <strong>{message.action.operation?.replace(/_/g, ' ')}</strong>
                {message.action.result && ` — ${message.action.result}`}
                {typeof message.action.confidence_score === 'number' && (
                  <> {`(confidence: ${Math.round(message.action.confidence_score * 100)}%, ${message.action.confidence_label || 'n/a'})`}</>
                )}
              </span>
              {message.action.explainability && (
                <div style={{ marginTop: '0.35rem', width: '100%', opacity: 0.9 }}>
                  {message.action.explainability}
                </div>
              )}
            </div>
          )}

          {!isUser && explain && (
            <div className="chat-action-badge" style={{ marginTop: '0.5rem' }}>
              <span>🧠</span>
              <span>
                Explain: {explain.formula || 'Computed from dataset'}
                {Array.isArray(explain.columns_used) && explain.columns_used.length > 0 && (
                  <> {` | Columns: ${explain.columns_used.join(', ')}`}</>
                )}
                {Array.isArray(explain.filters) && explain.filters.length > 0 && (
                  <> {` | Filters: ${explain.filters.join('; ')}`}</>
                )}
                {typeof explain.row_count === 'number' && (
                  <> {` | Rows: ${explain.row_count}`}</>
                )}
              </span>
            </div>
          )}

          {!isUser && drilldown?.available && (
            <div style={{ marginTop: '0.5rem' }}>
              <button
                className="chat-sample-btn"
                onClick={() => setShowDrilldown(prev => !prev)}
              >
                {showDrilldown ? 'Hide Drilldown' : 'Show Supporting Rows'}
              </button>

              {showDrilldown && (
                <div style={{ marginTop: '0.4rem', overflowX: 'auto', maxHeight: '220px' }}>
                  <div style={{ fontSize: '0.78rem', opacity: 0.85, marginBottom: '0.3rem' }}>
                    {drilldown.title || 'Supporting Rows'}
                  </div>
                  <table className="chat-manipulation-table" style={{ minWidth: '420px' }}>
                    <thead>
                      <tr>
                        {drillColumns.map((col) => (
                          <th key={col}>{col}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {drillRows.map((row, idx) => (
                        <tr key={idx}>
                          {drillColumns.map((col) => (
                            <td key={col}>{row[col] ?? '—'}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {!isUser && suggestions.length > 0 && (
            <div style={{ marginTop: '0.5rem' }}>
              <div style={{ fontSize: '0.78rem', opacity: 0.85, marginBottom: '0.3rem' }}>
                Try next:
              </div>
              <div style={{ display: 'flex', gap: '0.35rem', flexWrap: 'wrap' }}>
                {suggestions.slice(0, 4).map((s, i) => (
                  <button
                    key={`${s}-${i}`}
                    className="chat-sample-btn"
                    onClick={() => onFollowUp && onFollowUp(s)}
                    type="button"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
        <div className="chat-timestamp">
          {new Date(message.timestamp).toLocaleTimeString([], {
            hour: '2-digit',
            minute: '2-digit',
          })}
        </div>
      </div>
    </div>
  );
}

export default ChatMessage;