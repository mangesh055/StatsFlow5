/**
 * StatsFlow Home Page — Power BI-style Start Screen
 * ---------------------------------------------------
 * Shows Recent Projects, New Project options, and
 * quick-access features similar to Power BI Desktop.
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { useDropzone } from 'react-dropzone';
import { useData } from '../../context/DataContext';
import { uploadDataset, getSession, getReviewState } from '../../api/api';
import toast from 'react-hot-toast';
import './HomePage.css';

const ACCEPTED_TYPES = {
  'text/csv': ['.csv'],
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
  'application/vnd.ms-excel': ['.xls'],
};
const MAX_SIZE_MB = 50;
const RECENT_KEY = 'statsflow-recent-projects';

// ── Helpers ──────────────────────────────────────────────────────────────────
function getRecentProjects() {
  try {
    const raw = JSON.parse(localStorage.getItem(RECENT_KEY) || '[]');
    // Sanitize: ensure healthScore is always a number or null (not an object)
    return raw.map((p) => ({
      ...p,
      healthScore: typeof p.healthScore === 'object' && p.healthScore !== null
        ? p.healthScore?.total ?? null
        : p.healthScore ?? null,
    }));
  } catch {
    return [];
  }
}

function saveRecentProject(entry) {
  const existing = getRecentProjects();
  const filtered = existing.filter((p) => p.filename !== entry.filename);
  const updated = [entry, ...filtered].slice(0, 10);
  localStorage.setItem(RECENT_KEY, JSON.stringify(updated));
}

function formatTimeAgo(isoString) {
  if (!isoString) return '';
  const diff = Date.now() - new Date(isoString).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'Just now';
  if (mins < 60) return `${mins} min${mins > 1 ? 's' : ''} ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs} hr${hrs > 1 ? 's' : ''} ago`;
  const days = Math.floor(hrs / 24);
  if (days < 30) return `${days} day${days > 1 ? 's' : ''} ago`;
  return new Date(isoString).toLocaleDateString();
}

function fileIcon(filename) {
  if (!filename) return '📄';
  const ext = filename.split('.').pop().toLowerCase();
  if (ext === 'csv') return '📊';
  if (ext === 'xlsx' || ext === 'xls') return '📗';
  return '📄';
}

// ── Sub-components ────────────────────────────────────────────────────────────
function NewProjectTile({ icon, label, desc, onClick, highlight }) {
  return (
    <motion.button
      className={`home-new-tile ${highlight ? 'home-new-tile--primary' : ''}`}
      onClick={onClick}
      whileHover={{ y: -3, boxShadow: '0 8px 32px rgba(99,102,241,0.18)' }}
      whileTap={{ scale: 0.97 }}
    >
      <div className="home-new-tile-icon">{icon}</div>
      <div className="home-new-tile-label">{label}</div>
      {desc && <div className="home-new-tile-desc">{desc}</div>}
    </motion.button>
  );
}

function RecentRow({ project, onOpen, onRemove }) {
  return (
    <motion.tr
      className="home-recent-row"
      initial={{ opacity: 0, x: -10 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 10 }}
      whileHover={{ backgroundColor: 'rgba(99,102,241,0.06)' }}
    >
      <td className="home-recent-icon-cell">
        <span className="home-recent-file-icon">{fileIcon(project.filename)}</span>
      </td>
      <td className="home-recent-name-cell">
        <button className="home-recent-name-btn" onClick={() => onOpen(project)}>
          {project.filename}
        </button>
        <div className="home-recent-meta">
          {project.rows?.toLocaleString()} rows × {project.columns} cols
          {project.healthScore != null && typeof project.healthScore === 'number' && (
            <span className="home-recent-health">
              · Health {Number(project.healthScore).toFixed(1)}%
            </span>
          )}
        </div>
      </td>
      <td className="home-recent-location-cell">
        <span className="home-recent-location">Local Upload</span>
      </td>
      <td className="home-recent-time-cell">
        {formatTimeAgo(project.openedAt)}
      </td>
      <td className="home-recent-actions-cell">
        <button
          className="home-recent-remove-btn"
          title="Remove from recent"
          onClick={() => onRemove(project.filename)}
        >
          ✕
        </button>
      </td>
    </motion.tr>
  );
}

// ── Upload Modal ──────────────────────────────────────────────────────────────
function UploadModal({ onClose, onSuccess }) {
  const [isUploading, setIsUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [dragError, setDragError] = useState(null);
  const { setUploadData } = useData();
  const navigate = useNavigate();

  const processFile = useCallback(async (file) => {
    setIsUploading(true);
    setUploadProgress(0);
    setDragError(null);
    const toastId = toast.loading(`Uploading ${file.name}...`);
    try {
      const data = await uploadDataset(file, (pct) => setUploadProgress(pct));
      toast.success(
        `✅ Dataset loaded! ${data.shape.rows.toLocaleString()} rows × ${data.shape.columns} columns`,
        { id: toastId, duration: 5000 }
      );
      saveRecentProject({
        filename: file.name,
        rows: data.shape.rows,
        columns: data.shape.columns,
        healthScore: typeof data.health_score === 'object'
          ? data.health_score?.total ?? null
          : data.health_score ?? null,
        openedAt: new Date().toISOString(),
        sessionId: data.session_id,
      });
      setUploadData(data);
      onClose();
      navigate('/dashboard');
    } catch (err) {
      const msg = err.response?.data?.detail || 'Upload failed. Please try again.';
      toast.error(msg, { id: toastId });
      setDragError(msg);
    } finally {
      setIsUploading(false);
      setUploadProgress(0);
    }
  }, [setUploadData, navigate, onClose]);

  const onDrop = useCallback((acceptedFiles, rejectedFiles) => {
    if (rejectedFiles.length > 0) {
      setDragError(rejectedFiles[0]?.errors?.[0]?.message || 'Invalid file');
      return;
    }
    if (acceptedFiles.length > 0) processFile(acceptedFiles[0]);
  }, [processFile]);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: ACCEPTED_TYPES,
    maxSize: MAX_SIZE_MB * 1024 * 1024,
    multiple: false,
    disabled: isUploading,
  });

  return (
    <div className="home-modal-overlay" onClick={onClose}>
      <motion.div
        className="home-modal"
        onClick={(e) => e.stopPropagation()}
        initial={{ opacity: 0, scale: 0.9, y: 20 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.9, y: 20 }}
        transition={{ type: 'spring', stiffness: 300, damping: 25 }}
      >
        <div className="home-modal-header">
          <h2>Upload Dataset</h2>
          <button className="home-modal-close" onClick={onClose}>✕</button>
        </div>

        <div
          {...getRootProps()}
          className={[
            'home-modal-dropzone',
            isDragActive ? 'home-modal-dropzone--active' : '',
            isUploading ? 'home-modal-dropzone--uploading' : '',
            dragError ? 'home-modal-dropzone--error' : '',
          ].join(' ')}
        >
          <input {...getInputProps()} />
          {isUploading ? (
            <div className="home-modal-progress">
              <div className="home-modal-spinner" />
              <p>Processing dataset...</p>
              <div className="home-modal-bar-wrapper">
                <div className="home-modal-bar" style={{ width: `${uploadProgress}%` }} />
              </div>
              <span>{uploadProgress}% uploaded</span>
            </div>
          ) : isDragActive ? (
            <div className="home-modal-drag">
              <div className="home-modal-drag-icon">📂</div>
              <h3>Drop your file here!</h3>
              <p>Release to begin analysis</p>
            </div>
          ) : (
            <div className="home-modal-idle">
              <div className="home-modal-idle-icon">
                <span>📁</span>
              </div>
              <h3>Drag & Drop your dataset</h3>
              <p>or click to browse files</p>
              <div className="home-modal-formats">
                <span className="badge badge-info">CSV</span>
                <span className="badge badge-info">XLSX</span>
                <span className="badge badge-info">XLS</span>
              </div>
              <p className="home-modal-size-note">Max {MAX_SIZE_MB}MB</p>
            </div>
          )}
        </div>

        {dragError && (
          <div className="home-modal-error">⚠️ {dragError}</div>
        )}
      </motion.div>
    </div>
  );
}

// ── Main HomePage Component ───────────────────────────────────────────────────
function HomePage() {
  const navigate = useNavigate();
  const { setUploadData, setCleaningData, resetAll } = useData();

  const [recentProjects, setRecentProjects] = useState([]);
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [activeTab, setActiveTab] = useState('recent'); // 'recent' | 'shared'
  const [filterQuery, setFilterQuery] = useState('');
  const [greeting, setGreeting] = useState('');

  // Load recent projects from localStorage
  useEffect(() => {
    setRecentProjects(getRecentProjects());
  }, []);

  // Dynamic greeting
  useEffect(() => {
    const hour = new Date().getHours();
    if (hour < 12) setGreeting('Good morning');
    else if (hour < 17) setGreeting('Good afternoon');
    else setGreeting('Good evening');
  }, []);

  const handleRemoveRecent = (filename) => {
    const updated = recentProjects.filter((p) => p.filename !== filename);
    setRecentProjects(updated);
    localStorage.setItem(RECENT_KEY, JSON.stringify(updated));
  };

  const handleOpenRecent = async (project) => {
    if (!project.sessionId) {
      toast('This project does not have a saved session.', { icon: 'ℹ️' });
      return;
    }
    const toastId = toast.loading(`Resuming ${project.filename}...`);
    try {
      // Get base session details (raw data)
      const sessionData = await getSession(project.sessionId);
      
      if (!sessionData.success || !sessionData.raw) {
        throw new Error('Session data could not be retrieved');
      }

      setUploadData({
        session_id: sessionData.session_id,
        filename: sessionData.filename,
        shape: sessionData.raw.shape,
        health_score: sessionData.raw.health_score,
        columns_info: sessionData.raw.columns_info,
        data_preview: sessionData.raw.data_preview,
        column_names: sessionData.raw.column_names,
        quality_scorecard: null,
        anomaly_report: null,
      });

      // Try to get cleaned state if available
      if (sessionData.status !== 'uploaded') {
        try {
          const reviewData = await getReviewState(project.sessionId);
          if (reviewData.success) {
            setCleaningData({
              cleaned_shape: reviewData.cleaned_shape,
              cleaned_health_score: reviewData.cleaned_health_score,
              cleaning_report: reviewData.cleaning_report,
              pipeline_script: reviewData.pipeline_script || null,
              raw_preview: reviewData.raw_preview,
              cleaned_preview: reviewData.cleaned_preview,
              modified_cells: reviewData.modified_cells || [],
              change_log: reviewData.change_log || [],
              change_summary: reviewData.change_summary || null,
              review_summary: reviewData.review_summary || null,
              workflow_state: reviewData.workflow_state || null,
              status: reviewData.status || null,
              quality_scorecard: reviewData.quality_scorecard || null,
              anomaly_report: reviewData.anomaly_report || null,
              approval_guardrails: reviewData.approval_guardrails || null,
            });
            toast.success('Session resumed with cleaned data!', { id: toastId });
            navigate('/dashboard');
            return;
          }
        } catch (e) {
          console.warn('Could not load cleaned state, continuing with raw data', e);
        }
      }

      toast.success('Session resumed with raw data!', { id: toastId });
      navigate('/dashboard');
    } catch (err) {
      toast.error('Failed to resume session. Please re-upload.', { id: toastId });
    }
  };

  const filteredProjects = recentProjects.filter((p) =>
    p.filename?.toLowerCase().includes(filterQuery.toLowerCase())
  );

  const newProjectOptions = [
    {
      icon: '📤',
      label: 'Upload File',
      desc: 'CSV or Excel dataset',
      onClick: () => setShowUploadModal(true),
      highlight: true,
    },
    {
      icon: '📊',
      label: 'Blank Report',
      desc: 'Start fresh',
      onClick: () => setShowUploadModal(true),
    },
    {
      icon: '🗄️',
      label: 'SQL / Database',
      desc: 'Connect data source',
      onClick: () => toast('Database connection coming soon!', { icon: '🔧' }),
    },
    {
      icon: '☁️',
      label: 'Cloud Storage',
      desc: 'Import from cloud',
      onClick: () => toast('Cloud import coming soon!', { icon: '🔧' }),
    },
    {
      icon: '📋',
      label: 'Sample Dataset',
      desc: 'Try with demo data',
      onClick: () => toast('Sample datasets coming soon!', { icon: '🔧' }),
    },
  ];

  return (
    <div className="home-page">
      {/* ── Welcome Header ────────────────────────────────────────────── */}
      <motion.div
        className="home-welcome"
        initial={{ opacity: 0, y: -16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.45 }}
      >
        <div className="home-welcome-left">
          <div className="home-welcome-greeting">
            <span className="home-greeting-wave">👋</span>
            <span>{greeting}, welcome to</span>
          </div>
          <h1 className="home-welcome-title">
            Stats<span className="gradient-text">Flow</span>
          </h1>
          <p className="home-welcome-subtitle">
            Your intelligent data analytics platform — upload, clean, visualize &amp; chat with your data.
          </p>
        </div>
        <div className="home-welcome-stats">
          <div className="home-stat-card">
            <div className="home-stat-value">{recentProjects.length}</div>
            <div className="home-stat-label">Recent Projects</div>
          </div>
          <div className="home-stat-card">
            <div className="home-stat-value">4</div>
            <div className="home-stat-label">AI Features</div>
          </div>
          <div className="home-stat-card">
            <div className="home-stat-value">50MB</div>
            <div className="home-stat-label">Max File Size</div>
          </div>
        </div>
      </motion.div>

      {/* ── New Project Section ───────────────────────────────────────── */}
      <motion.section
        className="home-section"
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.45, delay: 0.1 }}
      >
        <div className="home-section-header">
          <div className="home-section-chevron">▼</div>
          <h2 className="home-section-title">Start new project</h2>
        </div>
        <div className="home-new-tiles">
          {newProjectOptions.map((opt) => (
            <NewProjectTile key={opt.label} {...opt} />
          ))}
        </div>
      </motion.section>

      {/* ── Recommended Section ───────────────────────────────────────── */}
      <motion.section
        className="home-section"
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.45, delay: 0.2 }}
      >
        <div className="home-section-header">
          <div className="home-section-chevron">▼</div>
          <h2 className="home-section-title">Recommended</h2>
          <div className="home-section-nav">
            <button className="home-nav-arrow" title="Previous">‹</button>
            <button className="home-nav-arrow" title="Next">›</button>
          </div>
        </div>
        <div className="home-recommended-cards">
          {[
            {
              icon: '🧹',
              title: 'Auto Data Cleaning',
              desc: 'Automatically imputes missing values, removes outliers, and generates a quality scorecard.',
              color: '#6366f1',
            },
            {
              icon: '📊',
              title: 'Smart Visualizations',
              desc: 'AI-recommended charts with trend detection and pattern highlights.',
              color: '#8b5cf6',
            },
            {
              icon: '🤖',
              title: 'AI Data Chat',
              desc: 'Ask questions about your dataset in plain English and get instant answers.',
              color: '#06b6d4',
            },
            {
              icon: '🐍',
              title: 'Export Pipeline',
              desc: 'Download a ready-to-run Python script for your entire cleaning pipeline.',
              color: '#10b981',
            },
          ].map((card) => (
            <motion.div
              key={card.title}
              className="home-recommended-card"
              whileHover={{ y: -4, boxShadow: `0 12px 36px ${card.color}22` }}
              style={{ '--card-color': card.color }}
            >
              <div
                className="home-rec-card-icon"
                style={{ background: `${card.color}18`, color: card.color }}
              >
                {card.icon}
              </div>
              <div className="home-rec-card-body">
                <div className="home-rec-card-title">{card.title}</div>
                <div className="home-rec-card-desc">{card.desc}</div>
              </div>
              <div
                className="home-rec-card-bar"
                style={{ background: card.color }}
              />
            </motion.div>
          ))}
        </div>
      </motion.section>

      {/* ── Recent Projects Section ───────────────────────────────────── */}
      <motion.section
        className="home-section home-section--recent"
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.45, delay: 0.3 }}
      >
        {/* Tab Bar */}
        <div className="home-recent-tabbar">
          <button
            className={`home-recent-tab ${activeTab === 'recent' ? 'home-recent-tab--active' : ''}`}
            onClick={() => setActiveTab('recent')}
          >
            <span className="home-tab-icon">🕐</span> Recent
          </button>
          <button
            className={`home-recent-tab ${activeTab === 'shared' ? 'home-recent-tab--active' : ''}`}
            onClick={() => setActiveTab('shared')}
          >
            <span className="home-tab-icon">👥</span> Shared with me
          </button>

          {/* Right: filter */}
          <div className="home-recent-toolbar">
            <div className="home-filter-input-wrapper">
              <span className="home-filter-icon">🔍</span>
              <input
                className="home-filter-input"
                placeholder="Filter by keyword"
                value={filterQuery}
                onChange={(e) => setFilterQuery(e.target.value)}
              />
            </div>
            <button className="home-filter-btn">
              ⚙ Filter
            </button>
          </div>
        </div>

        {/* Table */}
        {activeTab === 'recent' ? (
          filteredProjects.length > 0 ? (
            <div className="home-recent-table-wrapper">
              <table className="home-recent-table">
                <thead>
                  <tr>
                    <th style={{ width: 40 }}></th>
                    <th>Name</th>
                    <th>Location</th>
                    <th>Opened</th>
                    <th style={{ width: 40 }}></th>
                  </tr>
                </thead>
                <tbody>
                  <AnimatePresence>
                    {filteredProjects.map((p) => (
                      <RecentRow
                        key={p.filename + p.openedAt}
                        project={p}
                        onOpen={handleOpenRecent}
                        onRemove={handleRemoveRecent}
                      />
                    ))}
                  </AnimatePresence>
                </tbody>
              </table>
            </div>
          ) : (
            <motion.div
              className="home-empty-state"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
            >
              <div className="home-empty-icon">📂</div>
              <h3>No recent projects</h3>
              <p>Upload a dataset to get started. Your recent projects will appear here.</p>
              <button
                className="btn btn-primary"
                onClick={() => setShowUploadModal(true)}
              >
                📤 Upload your first dataset
              </button>
            </motion.div>
          )
        ) : (
          <motion.div
            className="home-empty-state"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
          >
            <div className="home-empty-icon">👥</div>
            <h3>No shared projects</h3>
            <p>Collaboration features are coming soon.</p>
          </motion.div>
        )}
      </motion.section>

      {/* ── Upload Modal ──────────────────────────────────────────────── */}
      <AnimatePresence>
        {showUploadModal && (
          <UploadModal
            onClose={() => setShowUploadModal(false)}
            onSuccess={() => setShowUploadModal(false)}
          />
        )}
      </AnimatePresence>
    </div>
  );
}

export default HomePage;
