/**
 * StatsFlow Dashboard — Phase 2 + Human-in-the-loop Review
 */

import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import toast from 'react-hot-toast';
import { useData } from '../../context/DataContext';
import {
  cleanDataset,
  downloadPipeline,
  downloadCleanedDataset,
  editCleanedCell,
  getReviewState,
  submitCleaningFeedback,
  revertSelectedChanges,
  finalizeCleanedDataset,
} from '../../api/api';
import HealthScoreCard from './HealthScoreCard';
import DataTable from './DataTable';
import DataViewerModal from '../Chatbot/DataViewerModal';
import './Dashboard.css';

const MISSING_STRATEGIES = [
  { value: 'mean', label: 'Mean', desc: 'Replace missing numerics with column mean' },
  { value: 'median', label: 'Median', desc: 'Replace missing numerics with column median' },
  { value: 'mode', label: 'Mode', desc: 'Replace missing values with most frequent value' },
  { value: 'knn', label: 'KNN', desc: 'K-Nearest Neighbors imputation (slower, stronger)' },
  { value: 'drop', label: 'Drop', desc: 'Remove all rows with any missing values' },
];

const OUTLIER_STRATEGIES = [
  { value: 'iqr', label: 'IQR', desc: 'Cap values outside [Q1-1.5xIQR, Q3+1.5xIQR]' },
  { value: 'zscore', label: 'Z-Score', desc: 'Replace values with |Z|>3 using column median' },
  { value: 'none', label: 'Skip', desc: 'Do not modify outlier values' },
];

function Dashboard() {
  const {
    sessionId,
    filename,
    rawShape,
    rawHealthScore,
    cleanedHealthScore,
    cleanedShape,
    columnsInfo,
    dataPreview,
    rawPreview,
    cleanedPreview,
    modifiedCells,
    editedCells,
    changeLog,
    changeSummary,
    workflowState,
    qualityScorecard,
    anomalyReport,
    approvalGuardrails,
    setCleaningData,
    updateState,
  } = useData();

  const navigate = useNavigate();

  const [missingStrategy, setMissingStrategy] = useState('mean');
  const [outlierStrategy, setOutlierStrategy] = useState('iqr');
  const [isCleaning, setIsCleaning] = useState(false);
  const [cleaningReport, setCleaningReport] = useState(null);
  const [isSavingEdit, setIsSavingEdit] = useState(false);
  const [isSubmittingReview, setIsSubmittingReview] = useState(false);
  const [loopMode, setLoopMode] = useState('guided');
  const [loopNotes, setLoopNotes] = useState('');
  const [changeDecisions, setChangeDecisions] = useState({});
  const [activeChangeIndex, setActiveChangeIndex] = useState(0);
  const [showDataViewer, setShowDataViewer] = useState(false);
  const [showRawDataViewer, setShowRawDataViewer] = useState(false);
  const [autoCleanError, setAutoCleanError] = useState('');
  const hasTriggeredInitialAutoClean = useRef(false);

  const hasCleaned = cleanedPreview.length > 0;

  const normalizeHealthScore = (incoming, fallback) => {
    if (incoming && typeof incoming === 'object') {
      return incoming;
    }
    if (typeof incoming === 'number') {
      const base = fallback && typeof fallback === 'object' ? fallback : {};
      return {
        ...base,
        total: incoming,
      };
    }
    return fallback;
  };

  const modifiedCellMap = useMemo(() => {
    const map = {};
    (modifiedCells || []).forEach((cell) => {
      map[`${cell.row}:${cell.column}`] = cell;
    });
    return map;
  }, [modifiedCells]);

  const editedCellMap = useMemo(() => {
    const map = {};
    (editedCells || []).forEach((cell) => {
      map[`${cell.row}:${cell.column}`] = cell;
    });
    return map;
  }, [editedCells]);

  const loadReviewState = async () => {
    const data = await getReviewState(sessionId);
    updateState({
      cleanedShape: data.cleaned_shape,
      cleanedHealthScore: data.cleaned_health_score,
      cleaningReport: data.cleaning_report,
      rawPreview: data.raw_preview || [],
      cleanedPreview: data.cleaned_preview || [],
      modifiedCells: data.modified_cells || [],
      changeLog: data.change_log || [],
      changeSummary: data.change_summary || null,
      reviewSummary: data.review_summary || null,
      workflowState: data.workflow_state || data.status || null,
      sessionStatus: data.status || null,
      qualityScorecard: data.quality_scorecard || qualityScorecard,
      anomalyReport: data.anomaly_report || anomalyReport,
      approvalGuardrails: data.approval_guardrails || approvalGuardrails,
      columnsInfo: data.columns_info || columnsInfo,
    });
  };

  const handleClean = async (useAuto = false) => {
    setIsCleaning(true);
    setAutoCleanError('');
    const toastId = toast.loading('Running cleaning pipeline...');

    try {
      const requestedMissing = useAuto ? 'auto' : missingStrategy;
      const requestedOutlier = useAuto ? 'auto' : outlierStrategy;
      const data = await cleanDataset(sessionId, requestedMissing, requestedOutlier);
      setCleaningData(data);
      setCleaningReport(data.cleaning_report);

      const appliedMissing = data?.cleaning_report?.missing_strategy || requestedMissing;
      const appliedOutlier = data?.cleaning_report?.outlier_strategy || requestedOutlier;
      setMissingStrategy(appliedMissing);
      setOutlierStrategy(appliedOutlier);

      updateState({
        cleaningStrategy: { missing: appliedMissing, outlier: appliedOutlier },
      });

      toast.success(
        `Cleaning complete: ${data.raw_health_score.total.toFixed(1)} -> ${data.cleaned_health_score.total.toFixed(1)}`,
        { id: toastId, duration: 5000 }
      );
    } catch (err) {
      const msg = err.response?.data?.detail || 'Cleaning failed.';
      if (useAuto) {
        setAutoCleanError(msg);
      }
      toast.error(msg, { id: toastId });
    } finally {
      setIsCleaning(false);
    }
  };

  useEffect(() => {
    if (!sessionId || hasCleaned || isCleaning || hasTriggeredInitialAutoClean.current) {
      return;
    }

    hasTriggeredInitialAutoClean.current = true;
    handleClean(true);
  }, [sessionId, hasCleaned, isCleaning]);

  const handleDownloadPipeline = async () => {
    const toastId = toast.loading('Generating pipeline script...');
    try {
      await downloadPipeline(sessionId, `statsflow_pipeline_${filename?.split('.')[0]}.py`);
      toast.success('Pipeline script downloaded.', { id: toastId });
    } catch {
      toast.error('Download failed.', { id: toastId });
    }
  };

  const handleEditCleanedCell = async (rowIndex, column, value) => {
    if (!hasCleaned || isSavingEdit) {
      return;
    }

    setIsSavingEdit(true);
    try {
      const data = await editCleanedCell(sessionId, rowIndex, column, value);

      const currentEdited = editedCells || [];
      const filtered = currentEdited.filter(
        c => !(c.row === data.edited_cell.row && c.column === data.edited_cell.column)
      );

      updateState({
        cleanedPreview: data.cleaned_preview || [],
        columnsInfo: data.columns_info || columnsInfo,
        editedCells: [...filtered, data.edited_cell],
        cleanedHealthScore: normalizeHealthScore(data.cleaned_health_score, cleanedHealthScore),
        qualityScorecard: data.quality_scorecard ? { ...(qualityScorecard || {}), cleaned: data.quality_scorecard } : qualityScorecard,
        workflowState: data.status || workflowState,
      });

      toast.success(`Updated row ${rowIndex + 1}, column '${column}'`);
    } catch (err) {
      const msg = err.response?.data?.detail || 'Failed to update cleaned dataset cell.';
      toast.error(msg);
      throw err;
    } finally {
      setIsSavingEdit(false);
    }
  };

  const handleRevertOne = async (changeId) => {
    const toastId = toast.loading('Reverting selected change...');
    try {
      const data = await revertSelectedChanges(sessionId, [changeId]);
      updateState({
        cleanedPreview: data.cleaned_preview || [],
        modifiedCells: data.modified_cells || [],
        changeLog: data.change_log || [],
        changeSummary: data.change_summary || null,
        cleanedHealthScore: normalizeHealthScore(data.cleaned_health_score, cleanedHealthScore),
        columnsInfo: data.columns_info || columnsInfo,
        workflowState: data.status || workflowState,
      });
      toast.success('Change reverted.', { id: toastId });
    } catch (err) {
      const msg = err.response?.data?.detail || 'Could not revert change.';
      toast.error(msg, { id: toastId });
    }
  };

  const handleRejectAll = async () => {
    const ids = (changeLog || [])
      .filter(c => c.change_type === 'cell_modified')
      .map(c => c.change_id);

    if (ids.length === 0) {
      toast('No cell-level changes available to revert.');
      return;
    }

    const toastId = toast.loading('Reverting all cell changes...');
    try {
      const data = await revertSelectedChanges(sessionId, ids);
      updateState({
        cleanedPreview: data.cleaned_preview || [],
        modifiedCells: data.modified_cells || [],
        changeLog: data.change_log || [],
        changeSummary: data.change_summary || null,
        cleanedHealthScore: normalizeHealthScore(data.cleaned_health_score, cleanedHealthScore),
        columnsInfo: data.columns_info || columnsInfo,
        workflowState: data.status || workflowState,
      });
      toast.success(`Reverted ${data.reverted_change_ids?.length || 0} changes.`, { id: toastId });
    } catch (err) {
      const msg = err.response?.data?.detail || 'Reject all failed.';
      toast.error(msg, { id: toastId });
    }
  };

  const handleKeepAll = async () => {
    const actions = (changeLog || [])
      .filter(c => c.change_type === 'cell_modified')
      .map(c => ({ change_id: c.change_id, action: 'keep' }));

    if (actions.length === 0) {
      toast('No cell-level changes to keep.');
      return;
    }

    setChangeDecisions(
      actions.reduce((acc, item) => {
        acc[item.change_id] = 'keep';
        return acc;
      }, {})
    );

    await handleSubmitFeedback('needs_changes', actions);
    toast.success('All detected changes marked as keep.');
  };

  const handleSubmitFeedback = async (approvalStatus, perChangeActions = []) => {
    setIsSubmittingReview(true);
    const toastId = toast.loading('Submitting review feedback...');

    try {
      await submitCleaningFeedback(sessionId, {
        approval_status: approvalStatus,
        trust_score: null,
        comments: loopNotes || null,
        strategy_feedback: null,
        per_change_actions: perChangeActions,
      });

      await loadReviewState();
      toast.success('Feedback saved.', { id: toastId });
    } catch (err) {
      const msg = err.response?.data?.detail || 'Could not submit feedback.';
      toast.error(msg, { id: toastId });
    } finally {
      setIsSubmittingReview(false);
    }
  };

  const handleApproveAndContinue = async () => {
    setIsSubmittingReview(true);
    const toastId = toast.loading('Finalizing approved dataset...');

    try {
      await submitCleaningFeedback(sessionId, {
        approval_status: 'approved',
        trust_score: null,
        comments: loopNotes || null,
        strategy_feedback: null,
        per_change_actions: Object.entries(changeDecisions).map(([change_id, action]) => ({
          change_id,
          action,
        })),
      });
      await finalizeCleanedDataset(sessionId, loopNotes || 'Approved from interaction loop.');
      await loadReviewState();

      toast.success('Dataset approved and finalized.', { id: toastId });
      navigate('/visualize');
    } catch (err) {
      const msg = err.response?.data?.detail || 'Approval/finalization failed.';
      toast.error(msg, { id: toastId });
    } finally {
      setIsSubmittingReview(false);
    }
  };

  const setDecision = (changeId, action) => {
    setChangeDecisions(prev => ({ ...prev, [changeId]: action }));
  };

  const actionableChanges = useMemo(
    () => (changeLog || []).filter(c => c.change_type === 'cell_modified'),
    [changeLog]
  );

  const currentGuidedChange = actionableChanges[activeChangeIndex] || null;

  const handleGuidedDecision = (action) => {
    if (!currentGuidedChange) return;
    setDecision(currentGuidedChange.change_id, action);
    setActiveChangeIndex(prev => {
      if (prev >= actionableChanges.length - 1) return prev;
      return prev + 1;
    });
  };

  const handleApplyLoopRound = async () => {
    const actions = Object.entries(changeDecisions).map(([change_id, action]) => ({
      change_id,
      action,
    }));

    if (actions.length === 0) {
      toast('Select at least one decision to apply this round.');
      return;
    }

    const revertIds = actions
      .filter(item => item.action === 'revert')
      .map(item => item.change_id);

    setIsSubmittingReview(true);
    const toastId = toast.loading('Applying review round...');

    try {
      if (revertIds.length > 0) {
        await revertSelectedChanges(sessionId, revertIds);
      }
      await handleSubmitFeedback('needs_changes', actions);
      setChangeDecisions({});
      setActiveChangeIndex(0);
      toast.success('Review round applied.', { id: toastId });
    } catch (err) {
      const msg = err.response?.data?.detail || 'Could not apply review round.';
      toast.error(msg, { id: toastId });
    } finally {
      setIsSubmittingReview(false);
    }
  };

  const topChanges = (changeLog || []).slice(0, 100);

  return (
    <div className="dashboard-page">
      <motion.div
        className="dashboard-header"
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <div>
          <h1 className="dashboard-title">Review Cleaning Results</h1>
          <p className="dashboard-subtitle">
            {filename} • {rawShape?.rows?.toLocaleString()} rows × {rawShape?.columns} columns
          </p>
          {workflowState && (
            <p className="dashboard-subtitle">Workflow state: <strong>{workflowState}</strong></p>
          )}
        </div>
        {hasCleaned && (
          <div className="dashboard-header-actions">
            <button className="btn btn-secondary" onClick={handleDownloadPipeline}>
              Export Pipeline
            </button>
            <button className="btn btn-primary" onClick={handleApproveAndContinue} disabled={isSubmittingReview}>
              Approve and Continue
            </button>
          </div>
        )}
      </motion.div>

      <div className="dashboard-content">
        <div className="dashboard-left">
          <motion.div initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.1 }}>
            <HealthScoreCard rawScore={rawHealthScore} cleanedScore={cleanedHealthScore} cleanedShape={cleanedShape} />
          </motion.div>

          {(qualityScorecard?.cleaned || qualityScorecard?.raw) && (
            <motion.div className="cleaning-report card" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
              <h3 className="cleaning-report-title">Data Quality Scorecard</h3>
              <div className="cleaning-report-stats">
                <div className="cleaning-stat">
                  <span className="cleaning-stat-value">
                    {(qualityScorecard?.raw?.dimensions?.completeness ?? 0).toFixed(1)}
                  </span>
                  <span className="cleaning-stat-label">Completeness</span>
                </div>
                <div className="cleaning-stat">
                  <span className="cleaning-stat-value">
                    {(qualityScorecard?.cleaned?.dimensions?.validity ?? qualityScorecard?.raw?.dimensions?.validity ?? 0).toFixed(1)}
                  </span>
                  <span className="cleaning-stat-label">Validity</span>
                </div>
                <div className="cleaning-stat">
                  <span className="cleaning-stat-value">
                    {(qualityScorecard?.cleaned?.dimensions?.uniqueness ?? qualityScorecard?.raw?.dimensions?.uniqueness ?? 0).toFixed(1)}
                  </span>
                  <span className="cleaning-stat-label">Uniqueness</span>
                </div>
                <div className="cleaning-stat">
                  <span className="cleaning-stat-value">
                    {(qualityScorecard?.cleaned?.dimensions?.timeliness ?? qualityScorecard?.raw?.dimensions?.timeliness ?? 0).toFixed(1)}
                  </span>
                  <span className="cleaning-stat-label">Timeliness</span>
                </div>
              </div>
            </motion.div>
          )}

          {(anomalyReport?.summary || approvalGuardrails) && (
            <motion.div className="cleaning-report card" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
              <h3 className="cleaning-report-title">Anomaly & Approval Signals</h3>
              <div className="cleaning-report-stats">
                <div className="cleaning-stat">
                  <span className="cleaning-stat-value">{anomalyReport?.summary?.high || 0}</span>
                  <span className="cleaning-stat-label">High Severity</span>
                </div>
                <div className="cleaning-stat">
                  <span className="cleaning-stat-value">{anomalyReport?.summary?.medium || 0}</span>
                  <span className="cleaning-stat-label">Medium Severity</span>
                </div>
                <div className="cleaning-stat">
                  <span className="cleaning-stat-value">{anomalyReport?.summary?.total_findings || 0}</span>
                  <span className="cleaning-stat-label">Total Findings</span>
                </div>
                <div className="cleaning-stat">
                  <span className="cleaning-stat-value">{approvalGuardrails?.low_confidence_changes || 0}</span>
                  <span className="cleaning-stat-label">Low-Confidence Fixes</span>
                </div>
              </div>
            </motion.div>
          )}

          <motion.div
            className="cleaning-config card"
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: 0.2 }}
          >
            <h3 className="cleaning-config-title">Cleaning Strategy</h3>
            <p className="cleaning-config-desc">
              {!hasCleaned
                ? 'Auto-cleaning runs automatically when you enter this step. After review, you can choose a strategy and re-run if needed.'
                : 'Review current results. If needed, choose a strategy and re-run before approval.'}
            </p>

            {!hasCleaned ? (
              <>
                <button className="btn btn-primary cleaning-run-btn" onClick={() => handleClean(true)} disabled={isCleaning}>
                  {isCleaning ? 'Auto-cleaning in progress...' : 'Retry Auto Cleaning'}
                </button>
                {autoCleanError && <p className="cleaning-strategy-desc">Auto-cleaning error: {autoCleanError}</p>}
              </>
            ) : (
              <>
                <div className="cleaning-config-section">
                  <label className="cleaning-config-label">Missing Value Strategy</label>
                  <div className="cleaning-strategy-grid">
                    {MISSING_STRATEGIES.map(s => (
                      <button
                        key={s.value}
                        className={`cleaning-strategy-btn ${missingStrategy === s.value ? 'active' : ''}`}
                        onClick={() => setMissingStrategy(s.value)}
                        disabled={isCleaning}
                        title={s.desc}
                      >
                        {s.label}
                      </button>
                    ))}
                  </div>
                  <p className="cleaning-strategy-desc">{MISSING_STRATEGIES.find(s => s.value === missingStrategy)?.desc}</p>
                </div>

                <div className="cleaning-config-section">
                  <label className="cleaning-config-label">Outlier Treatment</label>
                  <div className="cleaning-strategy-grid">
                    {OUTLIER_STRATEGIES.map(s => (
                      <button
                        key={s.value}
                        className={`cleaning-strategy-btn ${outlierStrategy === s.value ? 'active' : ''}`}
                        onClick={() => setOutlierStrategy(s.value)}
                        disabled={isCleaning}
                        title={s.desc}
                      >
                        {s.label}
                      </button>
                    ))}
                  </div>
                  <p className="cleaning-strategy-desc">{OUTLIER_STRATEGIES.find(s => s.value === outlierStrategy)?.desc}</p>
                </div>

                <button className="btn btn-primary cleaning-run-btn" onClick={() => handleClean(false)} disabled={isCleaning}>
                  {isCleaning ? 'Cleaning in progress...' : 'Re-run Cleaning'}
                </button>
              </>
            )}
          </motion.div>

          {hasCleaned && (
            <motion.div className="cleaning-report card" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
              <h3 className="cleaning-report-title">Review Actions</h3>
              <div className="cleaning-report-stats">
                <div className="cleaning-stat">
                  <span className="cleaning-stat-value">{changeSummary?.total_changes || 0}</span>
                  <span className="cleaning-stat-label">Total Changes</span>
                </div>
                <div className="cleaning-stat">
                  <span className="cleaning-stat-value">{changeSummary?.rows_removed || 0}</span>
                  <span className="cleaning-stat-label">Rows Removed</span>
                </div>
                <div className="cleaning-stat">
                  <span className="cleaning-stat-value">{changeSummary?.columns_dropped || 0}</span>
                  <span className="cleaning-stat-label">Columns Dropped</span>
                </div>
              </div>

              <div className="review-loop-modes">
                <button
                  className={`cleaning-strategy-btn ${loopMode === 'guided' ? 'active' : ''}`}
                  onClick={() => setLoopMode('guided')}
                  disabled={isSubmittingReview}
                >
                  Guided loop
                </button>
                <button
                  className={`cleaning-strategy-btn ${loopMode === 'batch' ? 'active' : ''}`}
                  onClick={() => setLoopMode('batch')}
                  disabled={isSubmittingReview}
                >
                  Batch loop
                </button>
              </div>

              {loopMode === 'guided' && currentGuidedChange && (
                <div className="guided-loop-card">
                  <p className="guided-loop-title">
                    Change {activeChangeIndex + 1} / {actionableChanges.length}
                  </p>
                  <p className="guided-loop-line">
                    Row {currentGuidedChange.row ?? '-'} • {currentGuidedChange.column}
                  </p>
                  <p className="guided-loop-line">
                    {String(currentGuidedChange.before ?? '-')} {'->'} {String(currentGuidedChange.after ?? '-')}
                  </p>
                  <p className="guided-loop-line muted">Reason: {currentGuidedChange.reason_tag || currentGuidedChange.reason || '-'}</p>
                  <div className="dashboard-header-actions">
                    <button className="btn btn-secondary" onClick={() => handleGuidedDecision('keep')}>Keep</button>
                    <button className="btn btn-secondary" onClick={() => handleGuidedDecision('revert')}>Revert</button>
                    <button className="btn btn-secondary" onClick={() => setActiveChangeIndex(prev => Math.max(prev - 1, 0))}>Prev</button>
                    <button className="btn btn-secondary" onClick={() => setActiveChangeIndex(prev => Math.min(prev + 1, Math.max(actionableChanges.length - 1, 0)))}>Next</button>
                  </div>
                </div>
              )}

              <div className="review-form-grid">
                <label className="cleaning-config-label">Loop Notes (optional)</label>
                <textarea
                  className="review-input"
                  rows={3}
                  placeholder="Example: Keep numeric imputations, revert age outlier changes"
                  value={loopNotes}
                  onChange={(e) => setLoopNotes(e.target.value)}
                />
              </div>

              <div className="dashboard-header-actions">
                <button className="btn btn-secondary" onClick={() => handleSubmitFeedback('approved')} disabled={isSubmittingReview}>
                  Accept All
                </button>
                <button className="btn btn-secondary" onClick={handleKeepAll} disabled={isSubmittingReview}>
                  Keep All Changes
                </button>
                <button className="btn btn-secondary" onClick={handleRejectAll} disabled={isSubmittingReview}>
                  Reject All
                </button>
                <button className="btn btn-secondary" onClick={handleApplyLoopRound} disabled={isSubmittingReview}>
                  Apply Loop Round
                </button>
                <button className="btn btn-secondary" onClick={() => handleSubmitFeedback('rerun')} disabled={isSubmittingReview}>
                  Re-run with New Strategy
                </button>
                <button className="btn btn-primary" onClick={handleApproveAndContinue} disabled={isSubmittingReview}>
                  Approve and Continue
                </button>
              </div>
            </motion.div>
          )}

          {cleaningReport && (
            <motion.div className="cleaning-report card" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
              <h3 className="cleaning-report-title">Cleaning Report</h3>
              <div className="cleaning-steps">
                {cleaningReport.steps?.map((step, idx) => (
                  <div key={idx} className="cleaning-step">
                    <div className="cleaning-step-num">{step.step}</div>
                    <div className="cleaning-step-desc">{step.description}</div>
                  </div>
                ))}
              </div>
            </motion.div>
          )}
        </div>

        <div className="dashboard-right">
          <motion.div className="column-profile card" initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.1 }}>
            <h3 className="column-profile-title">Column Profile</h3>
            <div className="column-profile-list">
              {columnsInfo?.map(col => (
                <div key={col.name} className="col-profile-row">
                  <div className="col-profile-info">
                    <span className="col-profile-name">{col.name}</span>
                    <span className={`badge ${col.type === 'numeric' ? 'badge-info' : 'badge-primary'}`} style={{ fontSize: '0.65rem' }}>
                      {col.type}
                    </span>
                  </div>
                  <div className="col-profile-meta">
                    <span>{col.missing_pct > 0 ? `${col.missing_pct}% null` : 'Complete'}</span>
                    <span className="col-profile-unique">{col.unique_count?.toLocaleString()} unique</span>
                  </div>
                </div>
              ))}
            </div>
          </motion.div>

          <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.2 }}>
            <DataTable
              data={rawPreview.length > 0 ? rawPreview : dataPreview}
              columnsInfo={columnsInfo}
              title="Original Data Preview"
              onFullscreen={() => setShowRawDataViewer(true)}
            />
          </motion.div>

          {cleanedPreview.length > 0 && (
            <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.25 }}>
              <DataTable
                data={cleanedPreview}
                columnsInfo={columnsInfo}
                title="Cleaned Data Preview"
                highlightedCells={modifiedCellMap}
                editedCells={editedCellMap}
                editable
                onEditCell={handleEditCleanedCell}
                onFullscreen={() => setShowDataViewer(true)}
                onDownload={() => downloadCleanedDataset(sessionId, `${filename?.split('.')[0]}_cleaned.csv`)}
              />
            </motion.div>
          )}

          {/* Data Viewer Modal */}
          <DataViewerModal
            isOpen={showDataViewer}
            data={cleanedPreview}
            columns={columnsInfo}
            title="Cleaned Data — Full View"
            onClose={() => setShowDataViewer(false)}
          />

          <DataViewerModal
            isOpen={showRawDataViewer}
            data={rawPreview.length > 0 ? rawPreview : dataPreview}
            columns={columnsInfo}
            title="Original Data — Full View"
            onClose={() => setShowRawDataViewer(false)}
          />

          {hasCleaned && (
            <div className="cleaned-legend card">
              <h4 className="cleaned-legend-title">Detailed Change Log</h4>
              <div className="change-log-table-wrap">
                <table className="change-log-table">
                  <thead>
                    <tr>
                      <th>Row</th>
                      <th>Column</th>
                      <th>Old Value</th>
                      <th>New Value</th>
                      <th>Reason</th>
                      <th>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {topChanges.map((change) => (
                      <tr key={change.change_id}>
                        <td>{change.row ?? '-'}</td>
                        <td>{change.column ?? '-'}</td>
                        <td>{String(change.before ?? '-')}</td>
                        <td>{String(change.after ?? '-')}</td>
                        <td>{change.reason_tag || change.reason || '-'}</td>
                        <td>
                          {change.change_type === 'cell_modified' ? (
                            <div className="change-action-group">
                              <button className="cell-edit-btn" onClick={() => setDecision(change.change_id, 'keep')}>
                                Keep
                              </button>
                              <button className="cell-edit-btn secondary" onClick={() => setDecision(change.change_id, 'revert')}>
                                Revert
                              </button>
                              <button className="cell-edit-btn" onClick={() => handleRevertOne(change.change_id)}>
                                Revert Now
                              </button>
                              <span className="loop-decision-pill">
                                {changeDecisions[change.change_id] || 'pending'}
                              </span>
                            </div>
                          ) : (
                            <span className="data-table-null">N/A</span>
                          )}
                        </td>
                      </tr>
                    ))}
                    {topChanges.length === 0 && (
                      <tr>
                        <td colSpan={6} className="data-table-null">No changes yet. Run cleaning to start review.</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default Dashboard;
