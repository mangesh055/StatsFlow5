/**
 * Data Health Score Card
 * -----------------------
 * Visual gauge showing the quality score (0-100) with dimension breakdown.
 * Shows both before and after cleaning when both scores are available.
 */

import React from 'react';
import { RadialBarChart, RadialBar, ResponsiveContainer, PolarAngleAxis } from 'recharts';

const SCORE_COLORS = {
  Excellent: '#10b981',
  Good:      '#6366f1',
  Fair:      '#f59e0b',
  Poor:      '#f97316',
  Critical:  '#ef4444',
};

const SCORE_LABELS = {
  Excellent: '🏆 Excellent',
  Good:      '✅ Good',
  Fair:      '⚠️ Fair',
  Poor:      '❌ Poor',
  Critical:  '🆘 Critical',
};

function ScoreGauge({ score, label, title }) {
  const color = SCORE_COLORS[label] || '#6366f1';
  const data = [{ value: score, fill: color }];

  return (
    <div className="health-gauge-card">
      <div className="health-gauge-title">{title}</div>
      <div className="health-gauge-chart">
        <ResponsiveContainer width="100%" height={160}>
          <RadialBarChart
            innerRadius="65%"
            outerRadius="100%"
            data={data}
            startAngle={210}
            endAngle={-30}
          >
            <PolarAngleAxis type="number" domain={[0, 100]} tick={false} />
            <RadialBar
              dataKey="value"
              cornerRadius={8}
              background={{ fill: '#f1f5f9' }}
            />
          </RadialBarChart>
        </ResponsiveContainer>
        <div className="health-gauge-overlay">
          <div className="health-gauge-score" style={{ color }}>
            {score?.toFixed(1)}
          </div>
          <div className="health-gauge-label" style={{ color }}>
            {SCORE_LABELS[label] || label}
          </div>
        </div>
      </div>
    </div>
  );
}

function DimensionBar({ label, value, color }) {
  return (
    <div className="health-dimension">
      <div className="health-dimension-header">
        <span className="health-dimension-label">{label}</span>
        <span className="health-dimension-value" style={{ color }}>
          {value?.toFixed(1)}%
        </span>
      </div>
      <div className="health-dimension-bar-track">
        <div
          className="health-dimension-bar-fill"
          style={{ width: `${value}%`, backgroundColor: color }}
        />
      </div>
    </div>
  );
}

function HealthScoreCard({ rawScore, cleanedScore, cleanedShape }) {
  const getDimensions = (score) => {
    if (!score) return [];
    const hasQualityDims = typeof score.validity === 'number' || typeof score.timeliness === 'number';
    const dims = hasQualityDims
      ? [
          { label: 'Completeness', key: 'completeness', weight: '35%' },
          { label: 'Validity', key: 'validity', weight: '30%' },
          { label: 'Uniqueness', key: 'uniqueness', weight: '20%' },
          { label: 'Timeliness', key: 'timeliness', weight: '15%' },
        ]
      : [
          { label: 'Completeness', key: 'completeness', weight: '40%' },
          { label: 'Uniqueness', key: 'uniqueness', weight: '20%' },
          { label: 'Consistency', key: 'consistency', weight: '20%' },
          { label: 'Outlier Score', key: 'outlier_score', weight: '20%' },
        ];
    return dims.map(d => ({
      ...d,
      value: score[d.key] || 0,
      color: score[d.key] >= 80 ? '#10b981'
           : score[d.key] >= 60 ? '#6366f1'
           : score[d.key] >= 40 ? '#f59e0b'
           : '#ef4444',
    }));
  };

  const improvement = cleanedScore && rawScore
    ? (cleanedScore.total - rawScore.total).toFixed(1)
    : null;

  const cleanedTotalCellsFallback = cleanedShape?.rows && cleanedShape?.columns
    ? cleanedShape.rows * cleanedShape.columns
    : null;

  const stats = [
    {
      key: 'missing_cells',
      label: 'Missing Cells',
      icon: '🕳️',
      before: rawScore?.missing_cells ?? 0,
      after: cleanedScore?.missing_cells ?? rawScore?.missing_cells ?? 0,
    },
    {
      key: 'duplicate_rows',
      label: 'Duplicate Rows',
      icon: '📋',
      before: rawScore?.duplicate_rows ?? 0,
      after: cleanedScore?.duplicate_rows ?? rawScore?.duplicate_rows ?? 0,
    },
    {
      key: 'total_cells',
      label: 'Total Cells',
      icon: '🗂️',
      before: rawScore?.total_cells ?? 0,
      after: cleanedScore?.total_cells ?? cleanedTotalCellsFallback ?? rawScore?.total_cells ?? 0,
    },
  ];

  return (
    <div className="health-score-card card">
      <div className="health-score-header">
        <h2 className="health-score-title">
          📊 Data Health Scorecard
        </h2>
        {improvement !== null && (
          <div className={`health-improvement ${parseFloat(improvement) >= 0 ? 'positive' : 'negative'}`}>
            {parseFloat(improvement) >= 0 ? '↑' : '↓'} {Math.abs(improvement)} pts after cleaning
          </div>
        )}
      </div>

      {/* Gauges Row */}
      <div className="health-gauges-row">
        {rawScore && (
          <ScoreGauge
            score={rawScore.total}
            label={rawScore.label}
            title="📥 Before Cleaning"
          />
        )}
        {cleanedScore && (
          <ScoreGauge
            score={cleanedScore.total}
            label={cleanedScore.label}
            title="✨ After Cleaning"
          />
        )}
      </div>

      {/* Dimension Breakdown (shows cleaned if available, else raw) */}
      <div className="health-dimensions">
        <div className="health-dimensions-title">
          Quality Dimensions {cleanedScore ? '(After Cleaning)' : '(Before Cleaning)'}
        </div>
        {getDimensions(cleanedScore || rawScore).map(dim => (
          <DimensionBar
            key={dim.key}
            label={`${dim.label} (weight: ${dim.weight})`}
            value={dim.value}
            color={dim.color}
          />
        ))}
      </div>

      {/* Quick Stats */}
      {(cleanedScore || rawScore) && (
        <div className="health-stats-grid">
          {stats.map(stat => (
            <div key={stat.key} className="health-stat">
              <div className="health-stat-icon">{stat.icon}</div>
              <div className="health-stat-label">{stat.label}</div>
              <div className="health-stat-compare">
                <div className="health-stat-row">
                  <span className="health-stat-row-label">Before</span>
                  <span className="health-stat-value">{Number(stat.before).toLocaleString()}</span>
                </div>
                <div className="health-stat-row">
                  <span className="health-stat-row-label">After</span>
                  <span className="health-stat-value after">{Number(stat.after).toLocaleString()}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default HealthScoreCard;