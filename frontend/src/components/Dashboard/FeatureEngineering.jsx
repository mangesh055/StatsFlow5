/**
 * FeatureEngineering.jsx
 * ----------------------
 * AI-powered feature engineering panel.
 * Shows LLM-generated feature suggestions, lets the user
 * accept/reject each one, then applies the approved set.
 */

import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import toast from 'react-hot-toast';
import { suggestFeatures, applyFeatures } from '../../api/api';
import './FeatureEngineering.css';

const OP_LABELS = {
  ratio: 'Ratio',
  difference: 'Difference',
  sum: 'Sum',
  product: 'Product',
  percentage: 'Percentage',
  interaction: 'Interaction',
  log1p: 'Log(1+x)',
  sqrt: 'Square Root',
  square: 'Square',
  abs: 'Absolute',
  normalize: 'Z-Score',
  inverse: 'Inverse',
  bin3: 'Bin (3 levels)',
  bin5: 'Bin (5 levels)',
};

const OP_COLORS = {
  ratio: '#6366f1',
  difference: '#f59e0b',
  sum: '#10b981',
  product: '#8b5cf6',
  percentage: '#3b82f6',
  interaction: '#ec4899',
  log1p: '#14b8a6',
  sqrt: '#06b6d4',
  square: '#f97316',
  abs: '#84cc16',
  normalize: '#a78bfa',
  inverse: '#fb923c',
  bin3: '#34d399',
  bin5: '#2dd4bf',
};

function FeatureCard({ feature, index, selected, onToggle }) {
  const opColor = OP_COLORS[feature.operation] || '#6366f1';
  const opLabel = OP_LABELS[feature.operation] || feature.operation;

  return (
    <motion.div
      className={`fe-card ${selected ? 'fe-card--selected' : ''}`}
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.05 }}
      onClick={() => onToggle(feature.name)}
    >
      <div className="fe-card__header">
        <div className="fe-card__name-row">
          <span className="fe-card__name">{feature.name}</span>
          <span className="fe-card__op-badge" style={{ background: opColor + '22', color: opColor, border: `1px solid ${opColor}44` }}>
            {opLabel}
          </span>
        </div>
        <div className={`fe-card__toggle ${selected ? 'fe-card__toggle--on' : ''}`}>
          {selected ? '✓ Selected' : 'Select'}
        </div>
      </div>

      <p className="fe-card__desc">{feature.description}</p>

      <div className="fe-card__meta">
        <span className="fe-card__cols-label">Columns used:</span>
        {feature.columns.map(c => (
          <span key={c} className="fe-card__col-pill">{c}</span>
        ))}
      </div>

      {feature.rationale && (
        <p className="fe-card__rationale">💡 {feature.rationale}</p>
      )}

      {feature.preview && feature.preview.length > 0 && (
        <div className="fe-card__preview">
          <span className="fe-card__preview-label">Preview (first 5):</span>
          <div className="fe-card__preview-values">
            {feature.preview.map((v, i) => (
              <span key={i} className="fe-card__preview-val">
                {v === null ? <em>null</em> : String(v)}
              </span>
            ))}
          </div>
        </div>
      )}
    </motion.div>
  );
}

function FeatureEngineering({ sessionId, onFeaturesApplied }) {
  const [phase, setPhase] = useState('idle'); // idle | loading | suggestions | applying | done
  const [suggestions, setSuggestions] = useState([]);
  const [selected, setSelected] = useState(new Set());
  const [applyLog, setApplyLog] = useState([]);
  const [newShape, setNewShape] = useState(null);

  const handleSuggest = async () => {
    setPhase('loading');
    const toastId = toast.loading('🤖 AI is analyzing your dataset…');
    try {
      const data = await suggestFeatures(sessionId);
      setSuggestions(data.suggestions || []);
      setSelected(new Set((data.suggestions || []).map(s => s.name))); // all pre-selected
      setPhase('suggestions');
      toast.success(`${data.suggestion_count} feature suggestions ready!`, { id: toastId, duration: 4000 });
    } catch (err) {
      const msg = err.response?.data?.detail || 'Failed to get feature suggestions.';
      toast.error(msg, { id: toastId });
      setPhase('idle');
    }
  };

  const toggleFeature = (name) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const handleSelectAll = () => setSelected(new Set(suggestions.map(s => s.name)));
  const handleSelectNone = () => setSelected(new Set());

  const handleApply = async () => {
    const chosen = suggestions.filter(s => selected.has(s.name));
    if (chosen.length === 0) {
      toast.error('Select at least one feature to apply.');
      return;
    }
    setPhase('applying');
    const toastId = toast.loading(`Applying ${chosen.length} features…`);
    try {
      const data = await applyFeatures(sessionId, chosen);
      setApplyLog(data.apply_log || []);
      setNewShape(data.new_shape);
      setPhase('done');
      toast.success(`${data.features_applied} feature(s) added to your dataset!`, { id: toastId, duration: 5000 });
      if (onFeaturesApplied) onFeaturesApplied(data);
    } catch (err) {
      const msg = err.response?.data?.detail || 'Failed to apply features.';
      toast.error(msg, { id: toastId });
      setPhase('suggestions');
    }
  };

  const handleReset = () => {
    setPhase('idle');
    setSuggestions([]);
    setSelected(new Set());
    setApplyLog([]);
    setNewShape(null);
  };

  return (
    <div className="fe-panel">
      {/* Header */}
      <div className="fe-header">
        <div>
          <h3 className="fe-title">🧬 AI Feature Engineering</h3>
          <p className="fe-subtitle">
            Let AI analyze your dataset and automatically suggest meaningful new features —
            ratios, transforms, interactions, and more.
          </p>
        </div>
        {phase === 'idle' && (
          <button className="fe-btn fe-btn--primary" onClick={handleSuggest}>
            ✨ Generate Features
          </button>
        )}
        {(phase === 'suggestions' || phase === 'done') && (
          <button className="fe-btn fe-btn--secondary" onClick={handleReset}>
            ↺ Start Over
          </button>
        )}
      </div>

      {/* Loading state */}
      {phase === 'loading' && (
        <div className="fe-loading">
          <div className="fe-spinner" />
          <p>AI is reading your data, running correlation analysis, and crafting feature ideas…</p>
        </div>
      )}

      {/* Suggestions */}
      <AnimatePresence>
        {phase === 'suggestions' && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            <div className="fe-toolbar">
              <span className="fe-toolbar__count">
                {selected.size} of {suggestions.length} selected
              </span>
              <div className="fe-toolbar__actions">
                <button className="fe-btn fe-btn--ghost" onClick={handleSelectAll}>Select All</button>
                <button className="fe-btn fe-btn--ghost" onClick={handleSelectNone}>Deselect All</button>
                <button
                  className="fe-btn fe-btn--primary"
                  onClick={handleApply}
                  disabled={selected.size === 0}
                >
                  Apply Selected ({selected.size})
                </button>
              </div>
            </div>

            <div className="fe-cards-grid">
              {suggestions.map((feat, i) => (
                <FeatureCard
                  key={feat.name}
                  feature={feat}
                  index={i}
                  selected={selected.has(feat.name)}
                  onToggle={toggleFeature}
                />
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Applying */}
      {phase === 'applying' && (
        <div className="fe-loading">
          <div className="fe-spinner" />
          <p>Applying selected features to your dataset…</p>
        </div>
      )}

      {/* Done */}
      {phase === 'done' && (
        <motion.div className="fe-done" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
          <div className="fe-done__banner">
            <span className="fe-done__icon">🎉</span>
            <div>
              <h4>Features Applied Successfully!</h4>
              {newShape && (
                <p>Dataset is now {newShape.rows.toLocaleString()} rows × {newShape.columns} columns</p>
              )}
            </div>
          </div>

          <div className="fe-done__log">
            {applyLog.map((item, i) => (
              <div key={i} className={`fe-log-item fe-log-item--${item.status}`}>
                <span className="fe-log-item__status">
                  {item.status === 'applied' ? '✅' : '❌'}
                </span>
                <div className="fe-log-item__info">
                  <strong>{item.name}</strong>
                  <span className="fe-log-item__op">{OP_LABELS[item.operation] || item.operation} on [{item.columns?.join(', ')}]</span>
                  {item.sample_values && (
                    <span className="fe-log-item__sample">
                      Sample: {item.sample_values.filter(v => v !== null).slice(0, 3).join(', ')}
                    </span>
                  )}
                  {item.error && <span className="fe-log-item__error">{item.error}</span>}
                </div>
              </div>
            ))}
          </div>

          <div className="fe-done__actions">
            <button className="fe-btn fe-btn--secondary" onClick={handleReset}>
              Generate More Features
            </button>
          </div>
        </motion.div>
      )}
    </div>
  );
}

export default FeatureEngineering;
