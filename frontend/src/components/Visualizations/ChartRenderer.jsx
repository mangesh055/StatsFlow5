/**
 * StatsFlow Chart Renderer
 * Renders all supported chart payloads with user customization support.
 */

import React, { useEffect, useMemo, useState } from 'react';
import {
  BarChart,
  Bar,
  AreaChart,
  Area,
  ComposedChart,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ScatterChart,
  Scatter,
  Cell,
  LineChart,
  Line,
  PieChart,
  Pie,
  Legend,
  RadarChart,
  Radar,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Treemap,
} from 'recharts';

const DEFAULT_PALETTE = ['#6366f1', '#8b5cf6', '#06b6d4', '#10b981', '#f59e0b', '#ef4444'];

const baseCardStyle = {
  background: 'var(--color-bg-card)',
  border: '1px solid var(--color-border)',
  borderRadius: '16px',
  padding: '20px',
  boxShadow: 'var(--shadow-sm)',
};

const hexToRgba = (hex, alpha = 1) => {
  const normalized = (hex || '').replace('#', '');
  if (![3, 6].includes(normalized.length)) {
    return `rgba(99, 102, 241, ${alpha})`;
  }
  const full = normalized.length === 3
    ? normalized.split('').map(c => c + c).join('')
    : normalized;
  const value = parseInt(full, 16);
  const r = (value >> 16) & 255;
  const g = (value >> 8) & 255;
  const b = value & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
};

const buildTheme = (customization, chartId, fallbackTitle) => {
  const palette = customization?.palette?.length ? customization.palette : DEFAULT_PALETTE;
  const title = customization?.titleOverrides?.[String(chartId)] || fallbackTitle;
  return {
    palette,
    title,
    titleColor: customization?.titleColor || 'var(--color-text-primary)',
    axisColor: customization?.axisColor || 'var(--color-text-muted)',
    gridColor: hexToRgba(customization?.axisColor || '#94a3b8', 0.25),
  };
};

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{
      background: 'var(--color-bg-card)',
      border: '1px solid var(--color-border)',
      borderRadius: '10px',
      padding: '10px 14px',
      boxShadow: 'var(--shadow-md)',
      fontSize: '12px',
      maxWidth: '220px',
      color: 'var(--color-text-primary)',
    }}>
      {label !== undefined && (
        <div style={{ fontWeight: 600, marginBottom: 6, color: 'var(--color-text-primary)', wordBreak: 'break-all' }}>
          {String(label)}
        </div>
      )}
      {payload.map((p, i) => (
        <div key={i} style={{ color: p.color || 'var(--color-primary)', marginBottom: 2 }}>
          <span style={{ color: 'var(--color-text-secondary)' }}>{p.name}: </span>
          <strong>
            {typeof p.value === 'number'
              ? p.value.toLocaleString(undefined, { maximumFractionDigits: 4 })
              : p.value}
          </strong>
        </div>
      ))}
    </div>
  );
};

const StatPill = ({ label, value }) => (
  <div style={{
    display: 'inline-flex',
    flexDirection: 'column',
    alignItems: 'center',
    padding: '4px 10px',
    background: 'var(--color-bg-muted)',
    border: '1px solid var(--color-border)',
    borderRadius: '20px',
    fontSize: '11px',
    marginRight: '8px',
    marginBottom: '10px',
  }}>
    <span style={{ color: 'var(--color-text-muted)', fontWeight: 500 }}>{label}</span>
    <span style={{ color: 'var(--color-text-primary)', fontWeight: 700 }}>{value}</span>
  </div>
);

const ChartHeader = ({ title, chart, titleColor, onRenameClick, onDeleteClick }) => {
  const [isEditing, setIsEditing] = useState(false);
  const [draftTitle, setDraftTitle] = useState(title || '');

  useEffect(() => {
    if (!isEditing) {
      setDraftTitle(title || '');
    }
  }, [title, isEditing]);

  const handleSave = () => {
    const nextTitle = draftTitle.trim();
    if (!nextTitle) {
      return;
    }
    onRenameClick?.(chart, nextTitle);
    setIsEditing(false);
  };

  const handleCancel = () => {
    setDraftTitle(title || '');
    setIsEditing(false);
  };

  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, marginBottom: '14px' }}>
      {isEditing ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 0 }}>
          <input
            type="text"
            value={draftTitle}
            onChange={(e) => setDraftTitle(e.target.value)}
            autoFocus
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                handleSave();
              } else if (e.key === 'Escape') {
                handleCancel();
              }
            }}
            style={{
              flex: 1,
              minWidth: 0,
              border: '1px solid var(--color-border)',
              borderRadius: '8px',
              background: 'var(--color-bg-card)',
              color: 'var(--color-text-primary)',
              fontSize: '0.9rem',
              fontWeight: 700,
              padding: '7px 10px',
            }}
          />
          <button
            type="button"
            onClick={handleSave}
            title="Save title"
            style={{
              border: '1px solid var(--color-border)',
              background: 'var(--color-bg-muted)',
              color: 'var(--color-success)',
              borderRadius: '8px',
              width: 30,
              height: 30,
              cursor: 'pointer',
              fontSize: '0.9rem',
              lineHeight: 1,
            }}
          >
            ✓
          </button>
          <button
            type="button"
            onClick={handleCancel}
            title="Cancel edit"
            style={{
              border: '1px solid var(--color-border)',
              background: 'var(--color-bg-muted)',
              color: 'var(--color-text-secondary)',
              borderRadius: '8px',
              width: 30,
              height: 30,
              cursor: 'pointer',
              fontSize: '0.9rem',
              lineHeight: 1,
            }}
          >
            ✕
          </button>
        </div>
      ) : (
        <div style={{ fontSize: '0.9rem', fontWeight: 700, color: titleColor, flex: 1, minWidth: 0 }}>{title}</div>
      )}
      {!isEditing && (
        <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
          {onRenameClick && (
            <button
              type="button"
              onClick={() => setIsEditing(true)}
              title="Rename chart"
              style={{
                border: '1px solid var(--color-border)',
                background: 'var(--color-bg-muted)',
                color: 'var(--color-text-secondary)',
                borderRadius: '8px',
                width: 30,
                height: 30,
                cursor: 'pointer',
                fontSize: '0.9rem',
                lineHeight: 1,
              }}
            >
              ✏️
            </button>
          )}
          {onDeleteClick && (
            <button
              type="button"
              onClick={() => onDeleteClick(chart)}
              title="Delete chart"
              style={{
                border: '1px solid var(--color-border)',
                background: 'var(--color-bg-muted)',
                color: 'var(--color-danger)',
                borderRadius: '8px',
                width: 30,
                height: 30,
                cursor: 'pointer',
                fontSize: '0.9rem',
                lineHeight: 1,
              }}
            >
              🗑️
            </button>
          )}
        </div>
      )}
    </div>
  );
};

function HistogramChart({ chart, customization, onRenameClick, onDeleteClick }) {
  const { data, stats } = chart;
  const theme = buildTheme(customization, chart.id, chart.title);
  if (!data || data.length === 0) return null;

  const tickInterval = Math.max(0, Math.floor(data.length / 8) - 1);

  return (
    <div style={baseCardStyle}>
      <ChartHeader title={theme.title} chart={chart} titleColor={theme.titleColor} onRenameClick={onRenameClick} onDeleteClick={onDeleteClick} />

      {stats && (
        <div style={{ marginBottom: 4 }}>
          {Object.entries(stats).map(([k, v]) => (
            <StatPill
              key={k}
              label={k.charAt(0).toUpperCase() + k.slice(1)}
              value={typeof v === 'number' ? v.toLocaleString(undefined, { maximumFractionDigits: 2 }) : v}
            />
          ))}
        </div>
      )}

      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={data} margin={{ top: 5, right: 10, left: -10, bottom: 50 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={theme.gridColor} vertical={false} />
          <XAxis dataKey="bin" tick={{ fontSize: 9, fill: theme.axisColor }} angle={-35} textAnchor="end" interval={tickInterval} label={{ value: 'Bin', position: 'insideBottomRight', offset: -10, fontSize: 10, fill: theme.axisColor }} />
          <YAxis tick={{ fontSize: 10, fill: theme.axisColor }} axisLine={false} tickLine={false} label={{ value: 'Count', angle: -90, position: 'insideLeft', fontSize: 10, fill: theme.axisColor }} />
          <Tooltip content={<CustomTooltip />} />
          <Bar dataKey="count" radius={[4, 4, 0, 0]} name="Count">
            {data.map((_, i) => (
              <Cell key={i} fill={hexToRgba(theme.palette[i % theme.palette.length], 0.75)} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function BarChartViz({ chart, customization, onRenameClick, onDeleteClick }) {
  const { data } = chart;
  const theme = buildTheme(customization, chart.id, chart.title);
  if (!data || data.length === 0) return null;

  return (
    <div style={baseCardStyle}>
      <ChartHeader title={theme.title} chart={chart} titleColor={theme.titleColor} onRenameClick={onRenameClick} onDeleteClick={onDeleteClick} />
      <ResponsiveContainer width="100%" height={Math.max(200, data.length * 36)}>
        <BarChart data={data} layout="vertical" margin={{ top: 5, right: 30, left: 10, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={theme.gridColor} horizontal={false} />
          <XAxis type="number" tick={{ fontSize: 10, fill: theme.axisColor }} axisLine={false} tickLine={false} label={{ value: 'Count', position: 'insideBottomRight', offset: -5, fontSize: 10, fill: theme.axisColor }} />
          <YAxis type="category" dataKey="category" tick={{ fontSize: 10, fill: theme.axisColor }} width={90} label={{ value: 'Category', angle: -90, position: 'insideLeft', fontSize: 10, fill: theme.axisColor }} />
          <Tooltip content={<CustomTooltip />} />
          <Bar dataKey="count" radius={[0, 6, 6, 0]} name="Count">
            {data.map((_, i) => (
              <Cell key={i} fill={theme.palette[i % theme.palette.length]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function ColumnChartViz({ chart, customization, onRenameClick, onDeleteClick }) {
  const { data, x_key = 'category', y_key = 'value' } = chart;
  const theme = buildTheme(customization, chart.id, chart.title);
  if (!data || data.length === 0) return null;

  return (
    <div style={baseCardStyle}>
      <ChartHeader title={theme.title} chart={chart} titleColor={theme.titleColor} onRenameClick={onRenameClick} onDeleteClick={onDeleteClick} />
      {chart.recommendation_reason && (
        <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 8 }}>
          {chart.recommendation_reason}
        </div>
      )}
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={data} margin={{ top: 10, right: 20, left: -10, bottom: 46 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={theme.gridColor} vertical={false} />
          <XAxis dataKey={x_key} tick={{ fontSize: 10, fill: theme.axisColor }} angle={-35} textAnchor="end" />
          <YAxis tick={{ fontSize: 10, fill: theme.axisColor }} axisLine={false} tickLine={false} />
          <Tooltip content={<CustomTooltip />} />
          <Bar dataKey={y_key} fill={theme.palette[0]} radius={[5, 5, 0, 0]} name={y_key} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function StackedColumnChartViz({ chart, customization, onRenameClick, onDeleteClick }) {
  const { data, x_key = 'category', series = [] } = chart;
  const theme = buildTheme(customization, chart.id, chart.title);
  if (!data || data.length === 0 || series.length === 0) return null;

  return (
    <div style={baseCardStyle}>
      <ChartHeader title={theme.title} chart={chart} titleColor={theme.titleColor} onRenameClick={onRenameClick} onDeleteClick={onDeleteClick} />
      {chart.recommendation_reason && (
        <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 8 }}>
          {chart.recommendation_reason}
        </div>
      )}
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={data} margin={{ top: 10, right: 20, left: -10, bottom: 48 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={theme.gridColor} vertical={false} />
          <XAxis dataKey={x_key} tick={{ fontSize: 10, fill: theme.axisColor }} angle={-30} textAnchor="end" />
          <YAxis tick={{ fontSize: 10, fill: theme.axisColor }} axisLine={false} tickLine={false} />
          <Tooltip content={<CustomTooltip />} />
          <Legend />
          {series.map((s, idx) => (
            <Bar key={s} dataKey={s} stackId="stack" fill={theme.palette[idx % theme.palette.length]} radius={idx === series.length - 1 ? [4, 4, 0, 0] : [0, 0, 0, 0]} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function LineChartViz({ chart, customization, onRenameClick, onDeleteClick }) {
  const { data, x_key = 'x', y_key = 'value', x_label } = chart;
  const theme = buildTheme(customization, chart.id, chart.title);
  if (!data || data.length === 0) return null;

  return (
    <div style={baseCardStyle}>
      <ChartHeader title={theme.title} chart={chart} titleColor={theme.titleColor} onRenameClick={onRenameClick} onDeleteClick={onDeleteClick} />
      {chart.recommendation_reason && (
        <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 8 }}>
          {chart.recommendation_reason}
        </div>
      )}
      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={data} margin={{ top: 10, right: 20, left: -10, bottom: 40 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={theme.gridColor} />
          <XAxis dataKey={x_key} tick={{ fontSize: 10, fill: theme.axisColor }} label={x_label ? { value: x_label, position: 'insideBottomRight', offset: -8, fontSize: 10, fill: theme.axisColor } : undefined} />
          <YAxis tick={{ fontSize: 10, fill: theme.axisColor }} axisLine={false} tickLine={false} />
          <Tooltip content={<CustomTooltip />} />
          <Line type="monotone" dataKey={y_key} stroke={theme.palette[0]} strokeWidth={2.5} dot={{ r: 2 }} activeDot={{ r: 4 }} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function AreaChartViz({ chart, customization, onRenameClick, onDeleteClick }) {
  const { data, x_key = 'x', y_key = 'value', x_label } = chart;
  const theme = buildTheme(customization, chart.id, chart.title);
  if (!data || data.length === 0) return null;

  return (
    <div style={baseCardStyle}>
      <ChartHeader title={theme.title} chart={chart} titleColor={theme.titleColor} onRenameClick={onRenameClick} onDeleteClick={onDeleteClick} />
      {chart.recommendation_reason && (
        <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 8 }}>
          {chart.recommendation_reason}
        </div>
      )}
      <ResponsiveContainer width="100%" height={260}>
        <AreaChart data={data} margin={{ top: 10, right: 20, left: -10, bottom: 40 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={theme.gridColor} />
          <XAxis dataKey={x_key} tick={{ fontSize: 10, fill: theme.axisColor }} label={x_label ? { value: x_label, position: 'insideBottomRight', offset: -8, fontSize: 10, fill: theme.axisColor } : undefined} />
          <YAxis tick={{ fontSize: 10, fill: theme.axisColor }} axisLine={false} tickLine={false} />
          <Tooltip content={<CustomTooltip />} />
          <Area type="monotone" dataKey={y_key} stroke={theme.palette[0]} fill={hexToRgba(theme.palette[0], 0.25)} strokeWidth={2} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function ComboChartViz({ chart, customization, onRenameClick, onDeleteClick }) {
  const {
    data,
    x_key = 'category',
    bar_key = 'bar_value',
    line_key = 'line_value',
    bar_label,
    line_label,
  } = chart;
  const theme = buildTheme(customization, chart.id, chart.title);
  if (!data || data.length === 0) return null;

  return (
    <div style={baseCardStyle}>
      <ChartHeader title={theme.title} chart={chart} titleColor={theme.titleColor} onRenameClick={onRenameClick} onDeleteClick={onDeleteClick} />
      {chart.recommendation_reason && (
        <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 8 }}>
          {chart.recommendation_reason}
        </div>
      )}
      <ResponsiveContainer width="100%" height={280}>
        <ComposedChart data={data} margin={{ top: 10, right: 20, left: -10, bottom: 46 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={theme.gridColor} vertical={false} />
          <XAxis dataKey={x_key} tick={{ fontSize: 10, fill: theme.axisColor }} angle={-30} textAnchor="end" />
          <YAxis tick={{ fontSize: 10, fill: theme.axisColor }} axisLine={false} tickLine={false} />
          <Tooltip content={<CustomTooltip />} />
          <Legend />
          <Bar dataKey={bar_key} fill={theme.palette[0]} name={bar_label || bar_key} radius={[4, 4, 0, 0]} />
          <Line type="monotone" dataKey={line_key} stroke={theme.palette[3] || theme.palette[1]} strokeWidth={2.5} dot={{ r: 2 }} name={line_label || line_key} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

function RadarChartViz({ chart, customization, onRenameClick, onDeleteClick }) {
  const { data, angle_key = 'subject', value_key = 'value' } = chart;
  const theme = buildTheme(customization, chart.id, chart.title);
  if (!data || data.length < 3) return null;

  return (
    <div style={baseCardStyle}>
      <ChartHeader title={theme.title} chart={chart} titleColor={theme.titleColor} onRenameClick={onRenameClick} onDeleteClick={onDeleteClick} />
      {chart.recommendation_reason && (
        <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 8 }}>
          {chart.recommendation_reason}
        </div>
      )}
      <ResponsiveContainer width="100%" height={300}>
        <RadarChart data={data} outerRadius="70%">
          <PolarGrid stroke={theme.gridColor} />
          <PolarAngleAxis dataKey={angle_key} tick={{ fill: theme.axisColor, fontSize: 10 }} />
          <PolarRadiusAxis tick={{ fill: theme.axisColor, fontSize: 10 }} />
          <Radar name={value_key} dataKey={value_key} stroke={theme.palette[0]} fill={hexToRgba(theme.palette[0], 0.3)} fillOpacity={1} />
          <Tooltip content={<CustomTooltip />} />
        </RadarChart>
      </ResponsiveContainer>
    </div>
  );
}

function TreemapChartViz({ chart, customization, onRenameClick, onDeleteClick }) {
  const { data, name_key = 'name', value_key = 'size' } = chart;
  const theme = buildTheme(customization, chart.id, chart.title);
  if (!data || data.length === 0) return null;

  const treeData = data.map(item => ({
    name: item[name_key],
    size: item[value_key],
  }));

  return (
    <div style={baseCardStyle}>
      <ChartHeader title={theme.title} chart={chart} titleColor={theme.titleColor} onRenameClick={onRenameClick} onDeleteClick={onDeleteClick} />
      {chart.recommendation_reason && (
        <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 8 }}>
          {chart.recommendation_reason}
        </div>
      )}
      <ResponsiveContainer width="100%" height={300}>
        <Treemap
          data={treeData}
          dataKey="size"
          stroke={hexToRgba(theme.palette[0], 0.5)}
          fill={hexToRgba(theme.palette[0], 0.7)}
        />
      </ResponsiveContainer>
    </div>
  );
}

function BubbleChartViz({ chart, customization, onRenameClick, onDeleteClick }) {
  const {
    data,
    x_key = 'x',
    y_key = 'y',
    size_key = 'size',
    x_label,
    y_label,
    size_label,
  } = chart;
  const theme = buildTheme(customization, chart.id, chart.title);
  if (!data || data.length === 0) return null;

  return (
    <div style={baseCardStyle}>
      <ChartHeader title={theme.title} chart={chart} titleColor={theme.titleColor} onRenameClick={onRenameClick} onDeleteClick={onDeleteClick} />
      {chart.recommendation_reason && (
        <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 8 }}>
          {chart.recommendation_reason}
        </div>
      )}
      <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 8 }}>
        Bubble size: {size_label || size_key}
      </div>
      <ResponsiveContainer width="100%" height={280}>
        <ScatterChart margin={{ top: 10, right: 20, left: -10, bottom: 20 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={theme.gridColor} />
          <XAxis
            type="number"
            dataKey={x_key}
            tick={{ fontSize: 10, fill: theme.axisColor }}
            label={{ value: x_label || x_key, position: 'insideBottom', offset: -3, fontSize: 10, fill: theme.axisColor }}
          />
          <YAxis
            type="number"
            dataKey={y_key}
            tick={{ fontSize: 10, fill: theme.axisColor }}
            label={{ value: y_label || y_key, angle: -90, position: 'insideLeft', fontSize: 10, fill: theme.axisColor }}
          />
          <Tooltip content={<CustomTooltip />} />
          <Scatter data={data} fill={theme.palette[2] || theme.palette[0]}>
            {data.map((point, idx) => (
              <Cell
                key={`bubble-${idx}`}
                r={Math.max(6, Number(point[size_key]) || 6)}
                fill={hexToRgba(theme.palette[idx % theme.palette.length], 0.65)}
              />
            ))}
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}

function PieChartViz({ chart, customization, onRenameClick, onDeleteClick }) {
  const { data, name_key = 'name', value_key = 'value' } = chart;
  const theme = buildTheme(customization, chart.id, chart.title);
  if (!data || data.length === 0) return null;

  return (
    <div style={baseCardStyle}>
      <ChartHeader title={theme.title} chart={chart} titleColor={theme.titleColor} onRenameClick={onRenameClick} onDeleteClick={onDeleteClick} />
      {chart.recommendation_reason && (
        <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 8 }}>
          {chart.recommendation_reason}
        </div>
      )}
      <ResponsiveContainer width="100%" height={300}>
        <PieChart>
          <Pie data={data} dataKey={value_key} nameKey={name_key} cx="50%" cy="48%" outerRadius={95} label={(entry) => `${entry[name_key]} (${entry.pct ?? ''}${entry.pct !== undefined ? '%' : ''})`}>
            {data.map((_, idx) => (
              <Cell key={`slice-${idx}`} fill={theme.palette[idx % theme.palette.length]} />
            ))}
          </Pie>
          <Tooltip content={<CustomTooltip />} />
          <Legend />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}

function ScatterPlot({ chart, customization, onRenameClick, onDeleteClick }) {
  const { data, x_col, y_col, correlation } = chart;
  const theme = buildTheme(customization, chart.id, chart.title);
  if (!data || data.length === 0) return null;

  const corrColor = Math.abs(correlation) >= 0.7
    ? '#10b981'
    : Math.abs(correlation) >= 0.4
      ? '#f59e0b'
      : 'var(--color-text-muted)';

  return (
    <div style={baseCardStyle}>
      <ChartHeader title={theme.title} chart={chart} titleColor={theme.titleColor} onRenameClick={onRenameClick} onDeleteClick={onDeleteClick} />

      <div style={{ marginBottom: 12, display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 11, color: 'var(--color-text-secondary)' }}>Pearson r:</span>
        <span style={{
          fontWeight: 700,
          color: corrColor,
          fontSize: 12,
          padding: '2px 10px',
          background: hexToRgba('#10b981', 0.12),
          borderRadius: '20px',
        }}>
          {correlation?.toFixed(4)}
        </span>
      </div>

      <ResponsiveContainer width="100%" height={240}>
        <ScatterChart margin={{ top: 10, right: 20, left: -10, bottom: 10 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={theme.gridColor} />
          <XAxis
            dataKey="x"
            name={x_col}
            type="number"
            tick={{ fontSize: 10, fill: theme.axisColor }}
            label={{ value: x_col, position: 'insideBottom', offset: -2, fontSize: 10, fill: theme.axisColor }}
          />
          <YAxis
            dataKey="y"
            name={y_col}
            type="number"
            tick={{ fontSize: 10, fill: theme.axisColor }}
            label={{ value: y_col, angle: -90, position: 'insideLeft', fontSize: 10, fill: theme.axisColor }}
          />
          <Tooltip content={<CustomTooltip />} cursor={{ strokeDasharray: '3 3', stroke: theme.palette[0] }} />
          <Scatter data={data} fill={theme.palette[2] || theme.palette[0]} fillOpacity={0.6} strokeWidth={0} />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}

function BoxPlotTable({ chart, customization, onRenameClick, onDeleteClick }) {
  const { data } = chart;
  const theme = buildTheme(customization, chart.id, chart.title);
  if (!data || data.length === 0) return null;

  const headers = ['Column', 'Min', 'Q1', 'Median', 'Mean', 'Q3', 'Max', 'IQR'];
  const keys = ['column', 'min', 'q1', 'median', 'mean', 'q3', 'max', 'iqr'];

  const fmt = (v) => (typeof v === 'number' ? v.toLocaleString(undefined, { maximumFractionDigits: 3 }) : v);

  return (
    <div style={{ ...baseCardStyle, gridColumn: '1 / -1' }}>
      <ChartHeader title={theme.title} chart={chart} titleColor={theme.titleColor} onRenameClick={onRenameClick} onDeleteClick={onDeleteClick} />
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px', tableLayout: 'auto' }}>
          <thead>
            <tr>
              {headers.map(h => (
                <th key={h} style={{
                  padding: '10px 12px',
                  textAlign: h === 'Column' ? 'left' : 'right',
                  background: 'var(--color-bg-muted)',
                  borderBottom: '2px solid var(--color-border)',
                  fontWeight: 600,
                  color: 'var(--color-text-secondary)',
                  whiteSpace: 'nowrap',
                }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.map((row, i) => (
              <tr key={i} style={{ background: i % 2 === 0 ? 'var(--color-bg-card)' : 'var(--color-bg-muted)' }}>
                {keys.map((k) => (
                  <td key={k} style={{
                    padding: '8px 12px',
                    textAlign: k === 'column' ? 'left' : 'right',
                    fontWeight: k === 'column' ? 700 : 400,
                    color: k === 'column' ? (theme.palette[0] || 'var(--color-primary)') : 'var(--color-text-secondary)',
                    borderBottom: '1px solid var(--color-border)',
                    whiteSpace: 'nowrap',
                  }}>
                    {fmt(row[k])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function CorrelationHeatmap({ chart, customization, onRenameClick, onDeleteClick }) {
  const { columns: cols, data } = chart;
  const [hoveredCell, setHoveredCell] = useState(null);
  const theme = buildTheme(customization, chart.id, chart.title);

  if (!cols || !data) return null;

  const getCell = (x, y) => data.find(d => d.x === x && d.y === y)?.value ?? 0;

  const positive = theme.palette[0] || '#6366f1';
  const negative = '#ef4444';

  const getCellBg = (v) => {
    const abs = Math.abs(v);
    if (v >= 0) return hexToRgba(positive, abs * 0.85);
    return hexToRgba(negative, abs * 0.85);
  };

  const getCellTextColor = (v) => (Math.abs(v) > 0.45 ? '#ffffff' : 'var(--color-text-primary)');
  const CELL_SIZE = Math.max(36, Math.min(56, Math.floor(440 / cols.length)));

  return (
    <div style={{ ...baseCardStyle, gridColumn: '1 / -1' }}>
      <ChartHeader title={theme.title} chart={chart} titleColor={theme.titleColor} onRenameClick={onRenameClick} onDeleteClick={onDeleteClick} />

      {hoveredCell && (
        <div style={{
          marginBottom: 10,
          padding: '6px 14px',
          background: hexToRgba(positive, 0.15),
          borderRadius: '8px',
          fontSize: 12,
          color: 'var(--color-text-secondary)',
          display: 'inline-block',
        }}>
          <strong style={{ color: positive }}>{hoveredCell.y}</strong>
          {' × '}
          <strong style={{ color: positive }}>{hoveredCell.x}</strong>
          {' = '}
          <strong style={{ color: hoveredCell.v >= 0 ? positive : negative }}>{hoveredCell.v.toFixed(4)}</strong>
        </div>
      )}

      <div style={{ overflowX: 'auto', overflowY: 'auto', maxHeight: 480 }}>
        <table style={{ borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th style={{ width: 80, minWidth: 80, padding: '4px 8px' }} />
              {cols.map(c => (
                <th key={c} style={{
                  padding: '6px 4px',
                  textAlign: 'center',
                  fontWeight: 600,
                  color: theme.axisColor,
                  fontSize: 9,
                  width: CELL_SIZE,
                  minWidth: CELL_SIZE,
                  maxWidth: CELL_SIZE,
                  overflow: 'hidden',
                  whiteSpace: 'nowrap',
                  textOverflow: 'ellipsis',
                }}>{c.length > 9 ? c.slice(0, 8) + '…' : c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {cols.map(rowCol => (
              <tr key={rowCol}>
                <td style={{
                  padding: '4px 8px',
                  fontWeight: 600,
                  color: theme.axisColor,
                  fontSize: 9,
                  whiteSpace: 'nowrap',
                  textAlign: 'right',
                  maxWidth: 80,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                }}>{rowCol.length > 12 ? rowCol.slice(0, 11) + '…' : rowCol}</td>
                {cols.map(colCol => {
                  const v = getCell(colCol, rowCol);
                  const isDiag = rowCol === colCol;
                  return (
                    <td
                      key={colCol}
                      title={`${rowCol} × ${colCol} = ${v.toFixed(4)}`}
                      onMouseEnter={() => setHoveredCell({ x: colCol, y: rowCol, v })}
                      onMouseLeave={() => setHoveredCell(null)}
                      style={{
                        width: CELL_SIZE,
                        height: CELL_SIZE,
                        background: getCellBg(v),
                        textAlign: 'center',
                        fontWeight: isDiag ? 800 : 500,
                        color: getCellTextColor(v),
                        border: `1px solid ${hexToRgba('#ffffff', 0.12)}`,
                        fontSize: 9,
                        userSelect: 'none',
                      }}
                    >
                      {v.toFixed(2)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div style={{ marginTop: 12, display: 'flex', gap: 16, fontSize: 10, color: 'var(--color-text-muted)', flexWrap: 'wrap' }}>
        <span>Positive correlation</span>
        <span>Negative correlation</span>
        <span>Darker cells mean stronger relationships</span>
      </div>
    </div>
  );
}

function ChartRenderer({ chart, customization, onRenameClick, onDeleteClick }) {
  const normalizedChart = useMemo(() => {
    if (!chart) return null;
    return {
      ...chart,
      id: chart.id ?? chart.title,
    };
  }, [chart]);

  if (!normalizedChart) return null;

  switch (normalizedChart.type) {
    case 'histogram':
      return <HistogramChart chart={normalizedChart} customization={customization} onRenameClick={onRenameClick} onDeleteClick={onDeleteClick} />;
    case 'bar':
      return <BarChartViz chart={normalizedChart} customization={customization} onRenameClick={onRenameClick} onDeleteClick={onDeleteClick} />;
    case 'column':
      return <ColumnChartViz chart={normalizedChart} customization={customization} onRenameClick={onRenameClick} onDeleteClick={onDeleteClick} />;
    case 'stacked_column':
      return <StackedColumnChartViz chart={normalizedChart} customization={customization} onRenameClick={onRenameClick} onDeleteClick={onDeleteClick} />;
    case 'line':
      return <LineChartViz chart={normalizedChart} customization={customization} onRenameClick={onRenameClick} onDeleteClick={onDeleteClick} />;
    case 'area':
      return <AreaChartViz chart={normalizedChart} customization={customization} onRenameClick={onRenameClick} onDeleteClick={onDeleteClick} />;
    case 'combo':
      return <ComboChartViz chart={normalizedChart} customization={customization} onRenameClick={onRenameClick} onDeleteClick={onDeleteClick} />;
    case 'pie':
      return <PieChartViz chart={normalizedChart} customization={customization} onRenameClick={onRenameClick} onDeleteClick={onDeleteClick} />;
    case 'radar':
      return <RadarChartViz chart={normalizedChart} customization={customization} onRenameClick={onRenameClick} onDeleteClick={onDeleteClick} />;
    case 'treemap':
      return <TreemapChartViz chart={normalizedChart} customization={customization} onRenameClick={onRenameClick} onDeleteClick={onDeleteClick} />;
    case 'bubble':
      return <BubbleChartViz chart={normalizedChart} customization={customization} onRenameClick={onRenameClick} onDeleteClick={onDeleteClick} />;
    case 'scatter':
      return <ScatterPlot chart={normalizedChart} customization={customization} onRenameClick={onRenameClick} onDeleteClick={onDeleteClick} />;
    case 'boxplot':
      return <BoxPlotTable chart={normalizedChart} customization={customization} onRenameClick={onRenameClick} onDeleteClick={onDeleteClick} />;
    case 'heatmap':
      return <CorrelationHeatmap chart={normalizedChart} customization={customization} onRenameClick={onRenameClick} onDeleteClick={onDeleteClick} />;
    default:
      return (
        <div style={{ ...baseCardStyle, color: 'var(--color-text-muted)', fontSize: 13, textAlign: 'center' }}>
          Unknown chart type: <code>{normalizedChart.type}</code>
        </div>
      );
  }
}

export default ChartRenderer;
