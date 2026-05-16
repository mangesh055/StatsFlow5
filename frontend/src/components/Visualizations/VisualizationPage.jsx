/**
 * StatsFlow Visualization Page — Phase 3
 * ----------------------------------------
 * Fetches chart payloads and AI insights from the backend and
 * renders them using ChartRenderer and InsightCard components.
 *
 * Three display modes (tabs):
 *   - Charts   : Grid of all generated charts
 *   - Insights : List of SLR-based and statistical text insights
 *   - Both     : Side-by-side layout on wide screens
 */

import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import toast from 'react-hot-toast';
import { useData } from '../../context/DataContext';
import { getVisualizations } from '../../api/api';
import ChartRenderer from './ChartRenderer';
import InsightCard from './InsightCard';
import InsertChartModal from './InsertChartModal';
import './Visualizations.css';

const THEME_PRESETS = {
  classic: ['#6366f1', '#8b5cf6', '#06b6d4', '#10b981', '#f59e0b', '#ef4444'],
  sunset: ['#f97316', '#fb7185', '#ef4444', '#f59e0b', '#facc15', '#14b8a6'],
  ocean: ['#0ea5e9', '#06b6d4', '#14b8a6', '#22c55e', '#6366f1', '#8b5cf6'],
  mono: ['#64748b', '#475569', '#334155', '#1e293b', '#0f172a', '#94a3b8'],
};

// ── Animation variants ────────────────────────────────────────────
const fadeUp = {
  hidden: { opacity: 0, y: 20 },
  visible: (i = 0) => ({
    opacity: 1,
    y: 0,
    transition: { delay: i * 0.07, duration: 0.35, ease: 'easeOut' },
  }),
};

function VisualizationPage() {
  const {
    sessionId,
    filename,
    cleanedShape,
    charts,
    recommendedCharts,
    insights,
    columnNames,
    cleanedPreview,
    dataPreview,
    setVisualizationData,
  } = useData();

  const navigate = useNavigate();

  const [isLoading, setIsLoading]   = useState(false);
  const [error, setError]           = useState(null);
  const [activeTab, setActiveTab]   = useState('charts');
  const [recommendedTypeFilter, setRecommendedTypeFilter] = useState('all');
  const [chartThemePreset, setChartThemePreset] = useState('classic');
  const [titleColor, setTitleColor] = useState('#0f172a');
  const [axisColor, setAxisColor] = useState('#64748b');
  const [titleOverrides, setTitleOverrides] = useState({});
  const [customCharts, setCustomCharts]     = useState([]);
  const [showInsertModal, setShowInsertModal] = useState(false);

  // ── Load visualizations (skip if already in context) ────────────
  const loadVisualizations = useCallback(async (force = false) => {
    if (!force && charts.length > 0) return;

    setIsLoading(true);
    setError(null);

    const toastId = toast.loading('📊 Generating charts and running regression analysis...');
    try {
      const data = await getVisualizations(sessionId);
      setVisualizationData(data);
      toast.success(
        `Generated ${data.charts.length} charts & ${data.insights.length} insights!`,
        { id: toastId, duration: 5000 }
      );
    } catch (err) {
      const msg = err.response?.data?.detail || 'Failed to generate visualizations.';
      setError(msg);
      toast.error(msg, { id: toastId });
    } finally {
      setIsLoading(false);
    }
  }, [sessionId, charts.length, setVisualizationData]);

  useEffect(() => {
    if (sessionId) loadVisualizations();
  }, [sessionId, loadVisualizations]);

  // ── Tab config ───────────────────────────────────────────────────
  const TABS = [
    { id: 'recommended', label: `⭐ Recommended`, count: recommendedCharts.length },
    { id: 'charts',   label: `📊 Charts`,   count: charts.length },
    { id: 'insights', label: `💡 Insights`, count: insights.length },
    { id: 'both',     label: `✨ Both`,     count: null },
  ];

  // ── Render chart grid ────────────────────────────────────────────
  const chartCustomization = {
    palette: THEME_PRESETS[chartThemePreset] || THEME_PRESETS.classic,
    titleColor,
    axisColor,
    titleOverrides,
  };

  const resetChartCustomization = () => {
    setChartThemePreset('classic');
    setTitleColor('#0f172a');
    setAxisColor('#64748b');
    setTitleOverrides({});
  };

  const handleRename = (targetChart, nextTitle) => {
    const chartId = String(targetChart.id);
    const trimmedTitle = nextTitle.trim();
    if (!trimmedTitle) { toast.error('Title cannot be empty.'); return; }
    setTitleOverrides(prev => ({ ...prev, [chartId]: trimmedTitle }));
    toast.success('Chart title updated.');
  };

  const handleDelete = (targetChart) => {
    if (targetChart.custom) {
      setCustomCharts(prev => prev.filter(c => c.id !== targetChart.id));
    } else {
      setVisualizationData({
        charts: charts.filter(c => c.id !== targetChart.id),
        recommendedCharts: recommendedCharts.filter(c => c.id !== targetChart.id),
      });
    }
    toast.success('Chart removed.');
  };

  const renderCharts = () => (
    <motion.div className="viz-charts-grid" initial="hidden" animate="visible">
      {/* Custom (user-inserted) charts */}
      {customCharts.map((chart, i) => (
        <motion.div key={chart.id} variants={fadeUp} custom={i}>
          <ChartRenderer chart={chart} customization={chartCustomization} onRenameClick={handleRename} onDeleteClick={handleDelete} />
        </motion.div>
      ))}
      {/* Backend-generated charts */}
      {charts.map((chart, i) => (
        <motion.div key={chart.id} variants={fadeUp} custom={customCharts.length + i}>
          <ChartRenderer chart={chart} customization={chartCustomization} onRenameClick={handleRename} onDeleteClick={handleDelete} />
        </motion.div>
      ))}
    </motion.div>
  );

  const renderRecommendedCharts = () => (
    <motion.div
      className="viz-charts-grid"
      initial="hidden"
      animate="visible"
    >
      {recommendedCharts
        .filter((chart) => recommendedTypeFilter === 'all' || chart.type === recommendedTypeFilter)
        .map((chart, i) => (
        <motion.div
          key={chart.id}
          variants={fadeUp}
          custom={i}
        >
          <ChartRenderer
            chart={chart}
            customization={chartCustomization}
            onRenameClick={handleRename}
            onDeleteClick={handleDelete}
          />
        </motion.div>
      ))}
    </motion.div>
  );

  // ── Render insights list ─────────────────────────────────────────
  const renderInsights = () => (
    <motion.div
      className="viz-insights-panel"
      initial="hidden"
      animate="visible"
    >
      <div className="viz-insights-header">
        <h3>🤖 Auto-Generated Analytical Insights</h3>
        <p>
          Powered by Simple Linear Regression, Pearson Correlation,
          and Statistical Distribution Analysis
        </p>
      </div>
      <div className="viz-insights-list">
        {insights.map((insight, i) => (
          <motion.div
            key={insight.id}
            variants={fadeUp}
            custom={i}
          >
            <InsightCard insight={insight} />
          </motion.div>
        ))}
      </div>
    </motion.div>
  );

  const hasData = charts.length > 0 || recommendedCharts.length > 0 || insights.length > 0;

  return (
    <div className="viz-page page-enter">
      {/* ── Page Header ────────────────────────────────────── */}
      <motion.div
        className="viz-header"
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35 }}
      >
        <div>
          <h1 className="viz-title">Charts &amp; Insights</h1>
          <p className="viz-subtitle">
            {filename}
            {cleanedShape && (
              <> &bull; {cleanedShape.rows?.toLocaleString()} rows &times; {cleanedShape.columns} columns</>
            )}
          </p>
        </div>

        <div className="viz-header-actions">
          <button
            className="btn btn-secondary"
            onClick={() => navigate('/dashboard')}
          >
            ← Back to Clean
          </button>
          <button
            className="btn btn-secondary"
            onClick={() => loadVisualizations(true)}
            disabled={isLoading}
            title="Regenerate all charts"
          >
            🔄 Refresh
          </button>
          <button
            className="btn btn-secondary"
            onClick={() => setShowInsertModal(true)}
            title="Insert a custom chart (Excel-style)"
          >
            📊 Insert Chart
          </button>
          <button
            className="btn btn-primary"
            onClick={() => navigate('/chat')}
          >
            🤖 Open AI Chat →
          </button>
        </div>
      </motion.div>

      {/* ── Loading ─────────────────────────────────────────── */}
      <AnimatePresence>
        {isLoading && (
          <motion.div
            className="viz-loading"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          >
            <div
              className="spinner spinner-dark"
              style={{ width: 44, height: 44 }}
            />
            <p>
              Computing histograms, correlation matrix, scatter plots,
              and running Simple Linear Regression on your cleaned data…
            </p>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Error ───────────────────────────────────────────── */}
      {error && !isLoading && (
        <motion.div
          className="viz-error"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
        >
          <p>⚠️ {error}</p>
          <button
            className="btn btn-primary"
            onClick={() => loadVisualizations(true)}
          >
            Retry
          </button>
        </motion.div>
      )}

      {/* ── Main Content ────────────────────────────────────── */}
      {!isLoading && hasData && (
        <>
          <div className="viz-customize card">
            <div className="viz-customize-header">
              <h3>Visualization Customization</h3>
              <button className="btn btn-secondary" onClick={resetChartCustomization}>
                Reset Styling
              </button>
            </div>

            <div className="viz-customize-grid">
              <div>
                <label className="viz-control-label">Theme preset</label>
                <select
                  className="viz-control"
                  value={chartThemePreset}
                  onChange={(e) => setChartThemePreset(e.target.value)}
                >
                  <option value="classic">Classic</option>
                  <option value="sunset">Sunset</option>
                  <option value="ocean">Ocean</option>
                  <option value="mono">Mono</option>
                </select>
              </div>

              <div>
                <label className="viz-control-label">Title color</label>
                <input
                  className="viz-control viz-color-input"
                  type="color"
                  value={titleColor}
                  onChange={(e) => setTitleColor(e.target.value)}
                />
              </div>

              <div>
                <label className="viz-control-label">Axis/text color</label>
                <input
                  className="viz-control viz-color-input"
                  type="color"
                  value={axisColor}
                  onChange={(e) => setAxisColor(e.target.value)}
                />
              </div>

            </div>
          </div>

          {/* Summary stats bar */}
          <motion.div
            style={{
              display:        'flex',
              gap:            12,
              marginBottom:   20,
              flexWrap:       'wrap',
            }}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.15 }}
          >
            {[
              { label: 'Charts Generated',    value: charts.length,   icon: '📊' },
              { label: 'Insights Discovered', value: insights.length, icon: '💡' },
              {
                label: 'SLR Trend Analyses',
                value: insights.filter(i => i.type === 'trend').length,
                icon: '📈',
              },
              { label: 'Recommended Charts', value: recommendedCharts.length, icon: '⭐' },
            ].map(stat => (
              <div key={stat.label} style={{
                display:        'flex',
                alignItems:     'center',
                gap:            8,
                padding:        '8px 16px',
                background:     'var(--color-bg-card)',
                border:         '1px solid var(--color-border)',
                borderRadius:   '10px',
                boxShadow:      '0 1px 4px rgba(0,0,0,0.05)',
                fontSize:       13,
              }}>
                <span>{stat.icon}</span>
                <strong style={{ color: 'var(--color-primary)' }}>{stat.value}</strong>
                <span style={{ color: 'var(--color-text-muted)' }}>{stat.label}</span>
              </div>
            ))}
          </motion.div>

          {/* Tabs */}
          <div className="viz-tabs">
            {TABS.map(tab => (
              <button
                key={tab.id}
                className={`viz-tab ${activeTab === tab.id ? 'active' : ''}`}
                onClick={() => setActiveTab(tab.id)}
              >
                {tab.label}
                {tab.count !== null && (
                  <span style={{
                    marginLeft:   6,
                    padding:      '1px 7px',
                    background:   activeTab === tab.id ? 'rgba(99,102,241,0.15)' : 'var(--color-bg-muted)',
                    borderRadius: '10px',
                    fontSize:     11,
                    fontWeight:   700,
                    color:        activeTab === tab.id ? 'var(--color-primary)' : 'var(--color-text-muted)',
                  }}>
                    {tab.count}
                  </span>
                )}
              </button>
            ))}
          </div>

          {/* Tab Content */}
          <AnimatePresence mode="wait">
            <motion.div
              key={activeTab}
              className="viz-content"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.25 }}
            >
              {activeTab === 'recommended' && (
                <div className="viz-type-picker">
                  {[
                    { id: 'all', label: 'All Charts' },
                    { id: 'column', label: 'Column' },
                    { id: 'line', label: 'Line' },
                    { id: 'area', label: 'Area' },
                    { id: 'pie', label: 'Pie' },
                    { id: 'bar', label: 'Bar' },
                    { id: 'scatter', label: 'X Y (Scatter)' },
                    { id: 'radar', label: 'Radar' },
                    { id: 'treemap', label: 'Treemap' },
                    { id: 'combo', label: 'Combo' },
                    { id: 'bubble', label: 'Bubble' },
                  ].map((item) => (
                    <button
                      key={item.id}
                      className={`viz-type-chip ${recommendedTypeFilter === item.id ? 'active' : ''}`}
                      onClick={() => setRecommendedTypeFilter(item.id)}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
              )}
              {activeTab === 'recommended' && renderRecommendedCharts()}
              {activeTab === 'charts' && renderCharts()}
              {activeTab === 'insights' && renderInsights()}
              {activeTab === 'both'     && (
                <div className="viz-content--both">
                  <div>
                    <h3 className="viz-split-title">⭐ Recommended Charts</h3>
                    {renderRecommendedCharts()}
                    <h3 className="viz-split-title" style={{ marginTop: 20 }}>📊 Charts</h3>
                    {renderCharts()}
                  </div>
                  {renderInsights()}
                </div>
              )}
            </motion.div>
          </AnimatePresence>
        </>
      )}

      {/* Excel-style Insert Chart Modal */}
      {showInsertModal && (
        <InsertChartModal
          columnNames={columnNames || []}
          previewRows={cleanedPreview?.length > 0 ? cleanedPreview : dataPreview}
          onInsert={(chart) => {
            setCustomCharts(prev => [chart, ...prev]);
            toast.success(`✅ "${chart.title}" added!`, { duration: 3000 });
            setActiveTab('charts');
          }}
          onClose={() => setShowInsertModal(false)}
        />
      )}

      {/* ── Empty state (after load but no data) ─────────── */}
      {!isLoading && !error && !hasData && (
        <div className="viz-empty">
          <div className="viz-empty-icon">📊</div>
          <h3>No visualizations yet</h3>
          <p>
            Ensure your dataset has at least one numeric column
            and has been cleaned first.
          </p>
          <button
            className="btn btn-primary"
            onClick={() => loadVisualizations(true)}
          >
            Generate Visualizations
          </button>
        </div>
      )}
    </div>
  );
}

export default VisualizationPage;
