/**
 * StatsFlow Global Data Context
 * --------------------------------
 * Provides application-wide state management using React Context API.
 * Stores session state, raw/cleaned data, charts, insights, and chat history.
 * This context is the "single source of truth" for the entire pipeline state.
 */

import React, { createContext, useContext, useState, useCallback, useEffect } from 'react';

// ── Create Context ──────────────────────────────────────────────────────────
const DataContext = createContext(null);

// ── Initial State ───────────────────────────────────────────────────────────
const initialState = {
  // Session tracking
  sessionId: null,
  currentStep: 0, // 0=upload, 1=dashboard, 2=visualize, 3=chat

  // Phase 1: Upload data
  filename: null,
  rawShape: null,
  rawHealthScore: null,
  columnsInfo: [],
  dataPreview: [],
  columnNames: [],

  // Phase 2: Cleaning
  cleanedShape: null,
  cleanedHealthScore: null,
  cleaningReport: null,
  pipelineScript: null,
  rawPreview: [],
  cleanedPreview: [],
  modifiedCells: [],
  changeLog: [],
  changeSummary: null,
  reviewSummary: null,
  workflowState: null,
  sessionStatus: null,
  editedCells: [],
  cleaningStrategy: { missing: 'mean', outlier: 'iqr' },
  qualityScorecard: null,
  anomalyReport: null,
  approvalGuardrails: null,

  // Phase 3: Visualizations
  charts: [],
  recommendedCharts: [],
  insights: [],

  // Phase 4: Chat
  messages: [],       // [{role, content, action, meta, timestamp}]
  isProcessing: false,
};

// ── Provider Component ──────────────────────────────────────────────────────
export function DataProvider({ children }) {
  const [state, setState] = useState(initialState);
  const [theme, setTheme] = useState(() => {
    const saved = window.localStorage.getItem('statsflow-theme');
    return saved === 'dark' ? 'dark' : 'light';
  });

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    window.localStorage.setItem('statsflow-theme', theme);
  }, [theme]);

  /**
   * Merge partial updates into the global state (shallow merge).
   * Avoids full state replacements for targeted updates.
   */
  const updateState = useCallback((updates) => {
    setState(prev => ({ ...prev, ...updates }));
  }, []);

  /**
   * Set Phase 1 data after a successful file upload.
   */
  const setUploadData = useCallback((data) => {
    updateState({
      sessionId: data.session_id,
      filename: data.filename,
      rawShape: data.shape,
      rawHealthScore: data.health_score,
      columnsInfo: data.columns_info,
      dataPreview: data.data_preview,
      columnNames: data.column_names,
      qualityScorecard: data.quality_scorecard || null,
      anomalyReport: data.anomaly_report || null,
      currentStep: 1,
    });
  }, [updateState]);

  /**
   * Set Phase 2 data after the cleaning pipeline completes.
   */
  const setCleaningData = useCallback((data) => {
    updateState({
      cleanedShape: data.cleaned_shape,
      cleanedHealthScore: data.cleaned_health_score,
      cleaningReport: data.cleaning_report,
      pipelineScript: data.pipeline_script,
      rawPreview: data.raw_preview || [],
      cleanedPreview: data.cleaned_preview,
      modifiedCells: data.modified_cells || [],
      changeLog: data.change_log || [],
      changeSummary: data.change_summary || null,
      reviewSummary: data.review_summary || null,
      workflowState: data.workflow_state || null,
      sessionStatus: data.status || null,
      qualityScorecard: data.quality_scorecard || null,
      anomalyReport: data.anomaly_report || null,
      approvalGuardrails: data.approval_guardrails || null,
      editedCells: [],
      currentStep: 2,
    });
  }, [updateState]);

  /**
   * Set Phase 3 data after visualization generation.
   */
  const setVisualizationData = useCallback((data) => {
    updateState({
      charts: data.charts,
      recommendedCharts: data.recommended_charts || [],
      insights: data.insights,
      currentStep: 3,
    });
  }, [updateState]);

  /**
   * Append a new message to the chat history.
   */
  const addMessage = useCallback((role, content, action = null, meta = null) => {
    const message = {
      id: Date.now(),
      role,           // 'user' | 'assistant'
      content,
      action,         // null or action details from agentic response
      meta,
      timestamp: new Date().toISOString(),
    };
    setState(prev => ({
      ...prev,
      messages: [...prev.messages, message],
    }));
    return message;
  }, []);

  /**
   * Reset everything back to the initial state (start over).
   */
  const resetAll = useCallback(() => {
    setState(initialState);
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme(prev => (prev === 'light' ? 'dark' : 'light'));
  }, []);

  const value = {
    ...state,
    updateState,
    setUploadData,
    setCleaningData,
    setVisualizationData,
    addMessage,
    resetAll,
    theme,
    toggleTheme,
    setTheme,
  };

  return (
    <DataContext.Provider value={value}>
      {children}
    </DataContext.Provider>
  );
}

/**
 * Custom hook to access the DataContext.
 * Must be used inside a <DataProvider>.
 */
export function useData() {
  const context = useContext(DataContext);
  if (!context) {
    throw new Error('useData must be used within a DataProvider');
  }
  return context;
}

export default DataContext;