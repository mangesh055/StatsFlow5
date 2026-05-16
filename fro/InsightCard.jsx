/**
 * StatsFlow Insight Card
 * -----------------------
 * Renders a single auto-generated insight with:
 *   - Type-coded left border and background
 *   - Expand/collapse for long bodies
 *   - Inline stats chips at the bottom
 *
 * Used by VisualizationPage to display SLR trend highlights,
 * distribution summaries, categorical profiles, and dataset overviews.
 */

import React, { useState } from 'react';

// ── Type-to-style mapping ────────────────────────────────────────
const TYPE_STYLES = {
  trend: {
    bg:     'rgba(99, 102, 241, 0.08)',
    border: '#6366f1',
    icon:   '📈',
  },
  distribution: {
    bg:     'rgba(6, 182, 212, 0.08)',
    border: '#06b6d4',
    icon:   '📊',
  },
  categorical: {
    bg:     'rgba(139, 92, 246, 0.08)',
    border: '#8b5cf6',
    icon:   '🏷️',
  },
  summary: {
    bg:     'rgba(16, 185, 129, 0.08)',
    border: '#10b981',
    icon:   '🗂️',
  },
};

// Characters before the "Read more" truncation kicks in
const TRUNCATE_AT = 200;

function InsightCard({ insight }) {
  const [expanded, setExpanded] = useState(false);

  if (!insight) return null;

  const style = TYPE_STYLES[insight.type] || TYPE_STYLES.summary;
  const body  = insight.body || '';
  const isLong = body.length > TRUNCATE_AT;

  const displayBody = isLong && !expanded
    ? body.slice(0, TRUNCATE_AT).trimEnd() + '…'
    : body;

  return (
    <div
      className="insight-card"
      style={{
        background:  style.bg,
        borderLeft:  `4px solid ${style.border}`,
      }}
    >
      {/* ── Header row (icon + title) ─────────────────────── */}
      <div className="insight-card-header">
        <span className="insight-icon" role="img" aria-label={insight.type}>
          {insight.icon || style.icon}
        </span>
        <h4 className="insight-title">{insight.title}</h4>
      </div>

      {/* ── Body text ────────────────────────────────────── */}
      <p className="insight-body">{displayBody}</p>

      {/* ── Read-more toggle ─────────────────────────────── */}
      {isLong && (
        <button
          className="insight-expand-btn"
          onClick={() => setExpanded(!expanded)}
          style={{ color: style.border }}
          aria-expanded={expanded}
        >
          {expanded ? '↑ Show less' : '↓ Read more'}
        </button>
      )}

      {/* ── Stats chips ──────────────────────────────────── */}
      {insight.stats && Object.keys(insight.stats).length > 0 && (
        <div className="insight-stats">
          {Object.entries(insight.stats)
            .slice(0, 5)
            .map(([key, val]) => (
              <div key={key} className="insight-stat">
                <span className="insight-stat-label">
                  {key.replace(/_/g, ' ')}
                </span>
                <span className="insight-stat-value">
                  {typeof val === 'number'
                    ? val % 1 === 0
                      ? val.toLocaleString()
                      : val.toLocaleString(undefined, { maximumFractionDigits: 4 })
                    : String(val)}
                </span>
              </div>
            ))}
        </div>
      )}
    </div>
  );
}

export default InsightCard;