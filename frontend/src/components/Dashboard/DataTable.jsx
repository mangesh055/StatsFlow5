/**
 * Paginated Data Preview Table
 * Supports two modes:
 *  1. LOCAL mode  — data supplied via `data` prop (small datasets, < PAGE_SIZE_THRESHOLD)
 *  2. SERVER mode — rows fetched on demand via `sessionId` + `getPagedData` API (large datasets)
 */

import React, { useState, useEffect, useCallback } from 'react';
import { getPagedData } from '../../api/api';

const LOCAL_PAGE_SIZE = 100;     // rows shown per page in local mode
const SERVER_PAGE_SIZE = 100;    // rows fetched per request in server mode
const SERVER_THRESHOLD = 500;    // if data.length >= this, switch to server mode

function DataTable({
  data,
  columnsInfo,
  title = 'Data Preview',
  highlightedCells = {},
  editedCells = {},
  editable = false,
  onEditCell = null,
  onFullscreen = null,
  onDownload = null,
  // Server-side pagination props
  sessionId = null,
  datasetType = 'cleaned',   // "cleaned" or "raw"
  totalRowsHint = null,      // total rows (from session metadata)
}) {
  // ── Server-side state ──────────────────────────────────────────
  const useServerPaging = Boolean(sessionId && (
    !data || data.length === 0 || data.length >= SERVER_THRESHOLD
  ));

  const [serverPage, setServerPage] = useState(0);
  const [serverData, setServerData] = useState(data || []);
  const [serverTotalRows, setServerTotalRows] = useState(totalRowsHint || (data?.length ?? 0));
  const [serverTotalPages, setServerTotalPages] = useState(1);
  const [serverColumnsInfo, setServerColumnsInfo] = useState(columnsInfo || []);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(null);

  // ── Local-mode state ───────────────────────────────────────────
  const [localPage, setLocalPage] = useState(0);

  // ── Cell editing state ─────────────────────────────────────────
  const [editingCell, setEditingCell] = useState(null);
  const [editingValue, setEditingValue] = useState('');
  const [savingCell, setSavingCell] = useState(null);

  // ── Fetch page from server ─────────────────────────────────────
  const fetchPage = useCallback(async (page) => {
    if (!sessionId) return;
    setLoading(true);
    setLoadError(null);
    try {
      const result = await getPagedData(sessionId, page, SERVER_PAGE_SIZE, datasetType);
      setServerData(result.rows || []);
      setServerTotalRows(result.total_rows || 0);
      setServerTotalPages(result.total_pages || 1);
      if (result.columns_info?.length) setServerColumnsInfo(result.columns_info);
    } catch (err) {
      setLoadError('Failed to load data. Please try again.');
    } finally {
      setLoading(false);
    }
  }, [sessionId, datasetType]);

  useEffect(() => {
    if (useServerPaging) {
      fetchPage(serverPage);
    }
  }, [useServerPaging, serverPage, fetchPage]);

  // Reset to page 0 if sessionId or datasetType changes
  useEffect(() => {
    setServerPage(0);
    setLocalPage(0);
  }, [sessionId, datasetType]);

  // ── Derived values ─────────────────────────────────────────────
  const activeData        = useServerPaging ? serverData : (data || []);
  const activeColumnsInfo = useServerPaging ? serverColumnsInfo : (columnsInfo || []);
  const activeTotalRows   = useServerPaging ? serverTotalRows : (data?.length ?? 0);
  const activeTotalPages  = useServerPaging
    ? serverTotalPages
    : Math.max(1, Math.ceil((data?.length ?? 0) / LOCAL_PAGE_SIZE));
  const activePage        = useServerPaging ? serverPage : localPage;

  const pageData = useServerPaging
    ? activeData   // server already sliced
    : (data || []).slice(localPage * LOCAL_PAGE_SIZE, (localPage + 1) * LOCAL_PAGE_SIZE);

  const pageStartRow = activePage * SERVER_PAGE_SIZE;

  if (!useServerPaging && (!data || data.length === 0)) return null;

  const columns = Object.keys(activeData[0] || pageData[0] || {});

  const getColType = (colName) => {
    const info = activeColumnsInfo?.find(c => c.name === colName);
    return info?.type || 'categorical';
  };

  const TYPE_BADGE = {
    numeric:     { label: 'NUM', cls: 'badge-info' },
    categorical: { label: 'CAT', cls: 'badge-primary' },
    datetime:    { label: 'DT',  cls: 'badge-success' },
  };

  const formatCell = (val) => {
    if (val === null || val === undefined) {
      return <span className="data-table-null">—</span>;
    }
    if (typeof val === 'number') {
      return Number.isInteger(val) ? val : val.toFixed(4);
    }
    return String(val);
  };

  const startEditing = (rowIndex, col, currentValue) => {
    if (!editable || !onEditCell) return;
    setEditingCell({ rowIndex, col });
    setEditingValue(currentValue === null || currentValue === undefined ? '' : String(currentValue));
  };

  const cancelEditing = () => {
    setEditingCell(null);
    setEditingValue('');
  };

  const saveEditing = async () => {
    if (!editingCell || !onEditCell) return;
    const payloadValue = editingValue.trim() === '' ? null : editingValue;
    const cellKey = `${editingCell.rowIndex}:${editingCell.col}`;
    setSavingCell(cellKey);
    try {
      await onEditCell(editingCell.rowIndex, editingCell.col, payloadValue);
      cancelEditing();
    } finally {
      setSavingCell(null);
    }
  };

  const goPrev = () => {
    if (useServerPaging) setServerPage(p => Math.max(0, p - 1));
    else setLocalPage(p => Math.max(0, p - 1));
  };

  const goNext = () => {
    if (useServerPaging) setServerPage(p => Math.min(activeTotalPages - 1, p + 1));
    else setLocalPage(p => Math.min(activeTotalPages - 1, p + 1));
  };

  return (
    <div className="data-table-card card">
      <div className="data-table-header">
        <h3 className="data-table-title">🗃️ {title}</h3>
        <div className="data-table-header-right">
          <span className="badge badge-primary">
            {activeTotalRows.toLocaleString()} rows total
          </span>
          {(onFullscreen || onDownload) && (
            <div className="data-table-actions">
              {onFullscreen && (
                <button className="data-table-action-btn" onClick={onFullscreen} title="View in fullscreen">
                  🗂️ Fullscreen
                </button>
              )}
              {onDownload && (
                <button className="data-table-action-btn" onClick={onDownload} title="Download as CSV">
                  📥 Download
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      {loadError && (
        <div style={{ padding: '12px 18px', color: 'var(--color-error, #f87171)', fontSize: '0.85rem' }}>
          ⚠️ {loadError}
        </div>
      )}

      <div className="data-table-wrapper" style={{ opacity: loading ? 0.6 : 1, transition: 'opacity 0.2s' }}>
        {loading && (
          <div style={{ textAlign: 'center', padding: '8px', fontSize: '0.8rem', color: 'var(--color-text-muted)' }}>
            Loading rows…
          </div>
        )}
        <table className="data-table">
          <thead>
            <tr>
              <th className="data-table-index-head">#</th>
              {columns.map(col => {
                const type = getColType(col);
                const badge = TYPE_BADGE[type] || TYPE_BADGE.categorical;
                return (
                  <th key={col}>
                    <div className="data-table-col-header">
                      <span className="data-table-col-name">{col}</span>
                      <span className={`badge ${badge.cls}`} style={{ fontSize: '0.65rem' }}>
                        {badge.label}
                      </span>
                    </div>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {pageData.map((row, rowIdx) => {
              const absoluteRowIndex = pageStartRow + rowIdx;
              return (
                <tr key={rowIdx} className={rowIdx % 2 === 0 ? 'even-row' : 'odd-row'}>
                  <td className="data-table-row-index">{absoluteRowIndex + 1}</td>
                  {columns.map(col => {
                    const cellKey = `${absoluteRowIndex}:${col}`;
                    const isAutoModified = Boolean(highlightedCells?.[cellKey]);
                    const isManualEdited = Boolean(editedCells?.[cellKey]);
                    const autoMeta = highlightedCells?.[cellKey];
                    const isEditing = editingCell?.rowIndex === absoluteRowIndex && editingCell?.col === col;
                    const isSaving = savingCell === cellKey;
                    const tdClass = [
                      isAutoModified ? 'cell-auto-modified' : '',
                      isManualEdited ? 'cell-manual-edited' : '',
                      editable ? 'cell-editable' : '',
                    ].filter(Boolean).join(' ');

                    return (
                      <td
                        key={col}
                        className={tdClass}
                        onDoubleClick={() => startEditing(absoluteRowIndex, col, row[col])}
                        title={
                          isAutoModified
                            ? `Auto change: ${autoMeta?.reason_tag || 'auto_cleaned'} (confidence ${(autoMeta?.confidence || 0).toFixed(2)})`
                            : (editable ? 'Double-click to edit cell' : undefined)
                        }
                      >
                        {isEditing ? (
                          <div className="cell-edit-wrap">
                            <input
                              className="cell-edit-input"
                              value={editingValue}
                              onChange={(e) => setEditingValue(e.target.value)}
                              autoFocus
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') saveEditing();
                                else if (e.key === 'Escape') cancelEditing();
                              }}
                            />
                            <button className="cell-edit-btn" onClick={saveEditing} disabled={isSaving}>
                              {isSaving ? '...' : 'Save'}
                            </button>
                            <button className="cell-edit-btn secondary" onClick={cancelEditing} disabled={isSaving}>
                              Cancel
                            </button>
                          </div>
                        ) : (
                          formatCell(row[col])
                        )}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {activeTotalPages > 1 && (
        <div className="data-table-pagination">
          <button
            className="btn btn-secondary"
            style={{ padding: '6px 14px', fontSize: '0.8rem' }}
            onClick={goPrev}
            disabled={activePage === 0 || loading}
          >
            ← Prev
          </button>
          <span className="data-table-page-info">
            Page {activePage + 1} of {activeTotalPages}
            {useServerPaging && (
              <span style={{ marginLeft: 8, fontSize: '0.75rem', opacity: 0.7 }}>
                (rows {pageStartRow + 1}–{Math.min(pageStartRow + SERVER_PAGE_SIZE, activeTotalRows)} of {activeTotalRows.toLocaleString()})
              </span>
            )}
          </span>
          <button
            className="btn btn-secondary"
            style={{ padding: '6px 14px', fontSize: '0.8rem' }}
            onClick={goNext}
            disabled={activePage >= activeTotalPages - 1 || loading}
          >
            Next →
          </button>
        </div>
      )}
    </div>
  );
}

export default DataTable;