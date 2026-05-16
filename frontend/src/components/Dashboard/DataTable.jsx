/**
 * Paginated Data Preview Table
 * Renders the first N rows of the dataset with column type badges.
 */

import React, { useState } from 'react';

const PAGE_SIZE = 10;

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
}) {
  const [page, setPage] = useState(0);
  const [editingCell, setEditingCell] = useState(null);
  const [editingValue, setEditingValue] = useState('');
  const [savingCell, setSavingCell] = useState(null);

  if (!data || data.length === 0) return null;

  const columns = Object.keys(data[0] || {});
  const totalPages = Math.ceil(data.length / PAGE_SIZE);
  const pageData = data.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  const getColType = (colName) => {
    const info = columnsInfo?.find(c => c.name === colName);
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
    if (!editable || !onEditCell) {
      return;
    }
    setEditingCell({ rowIndex, col });
    setEditingValue(currentValue === null || currentValue === undefined ? '' : String(currentValue));
  };

  const cancelEditing = () => {
    setEditingCell(null);
    setEditingValue('');
  };

  const saveEditing = async () => {
    if (!editingCell || !onEditCell) {
      return;
    }

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

  return (
    <div className="data-table-card card">
      <div className="data-table-header">
        <h3 className="data-table-title">🗃️ {title}</h3>
        <div className="data-table-header-right">
          <span className="badge badge-primary">
            {data.length} rows shown
          </span>
          {(onFullscreen || onDownload) && (
            <div className="data-table-actions">
              {onFullscreen && (
                <button
                  className="data-table-action-btn"
                  onClick={onFullscreen}
                  title="View in fullscreen"
                >
                  🗂️ Fullscreen
                </button>
              )}
              {onDownload && (
                <button
                  className="data-table-action-btn"
                  onClick={onDownload}
                  title="Download as CSV"
                >
                  📥 Download
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="data-table-wrapper">
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
              const absoluteRowIndex = page * PAGE_SIZE + rowIdx;
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
                              if (e.key === 'Enter') {
                                saveEditing();
                              } else if (e.key === 'Escape') {
                                cancelEditing();
                              }
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
            );})}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="data-table-pagination">
          <button
            className="btn btn-secondary"
            style={{ padding: '6px 14px', fontSize: '0.8rem' }}
            onClick={() => setPage(p => Math.max(0, p - 1))}
            disabled={page === 0}
          >
            ← Prev
          </button>
          <span className="data-table-page-info">
            Page {page + 1} of {totalPages}
          </span>
          <button
            className="btn btn-secondary"
            style={{ padding: '6px 14px', fontSize: '0.8rem' }}
            onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
            disabled={page >= totalPages - 1}
          >
            Next →
          </button>
        </div>
      )}
    </div>
  );
}

export default DataTable;