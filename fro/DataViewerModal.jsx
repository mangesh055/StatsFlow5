/**
 * DataViewerModal — Fullscreen Excel-like data viewer
 * -------------------------------------------------------
 * Displays tabular data in a modal with Excel-like features:
 * - Resizable columns
 * - Horizontal/vertical scrolling
 * - Search and filter
 * - Export to CSV
 */

import React, { useState, useCallback, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import './DataViewerModal.css';

function DataViewerModal({ isOpen, data = [], columns = [], title = 'Data Viewer', onClose }) {
  const [searchTerm, setSearchTerm] = useState('');
  const [sortColumn, setSortColumn] = useState(null);
  const [sortAsce, setSortAsc] = useState(true);
  const [currentPage, setCurrentPage] = useState(0);
  const [columnWidths, setColumnWidths] = useState({});

  const ROWS_PER_PAGE = 20;

  // Filter data based on search term
  const filteredData = useMemo(() => {
    if (!searchTerm.trim()) return data;
    
    const term = searchTerm.toLowerCase();
    return data.filter(row =>
      Object.values(row).some(val =>
        String(val).toLowerCase().includes(term)
      )
    );
  }, [data, searchTerm]);

  // Sort data
  const sortedData = useMemo(() => {
    if (!sortColumn) return filteredData;
    
    const sorted = [...filteredData].sort((a, b) => {
      const aVal = a[sortColumn];
      const bVal = b[sortColumn];
      
      const aNum = parseFloat(aVal);
      const bNum = parseFloat(bVal);
      const isNumeric = !isNaN(aNum) && !isNaN(bNum);
      
      let comparison = 0;
      if (isNumeric) {
        comparison = aNum - bNum;
      } else {
        comparison = String(aVal).localeCompare(String(bVal));
      }
      
      return sortAsce ? comparison : -comparison;
    });
    
    return sorted;
  }, [filteredData, sortColumn, sortAsce]);

  // Paginate data
  const totalPages = Math.max(1, Math.ceil(sortedData.length / ROWS_PER_PAGE));
  const paginatedData = sortedData.slice(
    currentPage * ROWS_PER_PAGE,
    (currentPage + 1) * ROWS_PER_PAGE
  );

  const handleColumnSort = useCallback((col) => {
    if (sortColumn === col) {
      setSortAsc(!sortAsce);
    } else {
      setSortColumn(col);
      setSortAsc(true);
    }
    setCurrentPage(0);
  }, [sortColumn, sortAsce]);

  const handleExportCSV = () => {
    if (!sortedData.length || !columns.length) return;

    const rows = [columns.map(c => c.name || c)];
    sortedData.forEach(row => {
      rows.push(columns.map(c => {
        const colName = c.name || c;
        const val = row[colName];
        // Escape quotes in CSV
        return typeof val === 'string' && val.includes(',')
          ? `"${val.replace(/"/g, '""')}"` 
          : val;
      }));
    });

    const csv = rows.map(r => r.join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.setAttribute('download', `${title}_export.csv`);
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
  };

  if (!isOpen) return null;

  const displayColumns = columns.length > 0 ? columns : Object.keys(data[0] || {});

  return (
    <AnimatePresence>
      <motion.div
        className="data-viewer-overlay"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={onClose}
      >
        <motion.div
          className="data-viewer-modal"
          initial={{ scale: 0.9, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          exit={{ scale: 0.9, opacity: 0 }}
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div className="dvm-header">
            <h2 className="dvm-title">{title}</h2>
            <button className="dvm-close-btn" onClick={onClose} title="Close (Esc)">
              ✕
            </button>
          </div>

          {/* Toolbar */}
          <div className="dvm-toolbar">
            <input
              type="text"
              className="dvm-search-input"
              placeholder="🔍 Search across all columns..."
              value={searchTerm}
              onChange={(e) => {
                setSearchTerm(e.target.value);
                setCurrentPage(0);
              }}
            />
            <button className="dvm-export-btn" onClick={handleExportCSV} title="Export to CSV">
              📥 Export
            </button>
          </div>

          {/* Table */}
          <div className="dvm-table-container">
            <table className="dvm-table">
              <thead>
                <tr>
                  {displayColumns.map((col) => {
                    const colName = col.name || col;
                    const isActive = sortColumn === colName;
                    return (
                      <th
                        key={colName}
                        className={`dvm-th ${isActive ? 'active' : ''}`}
                        onClick={() => handleColumnSort(colName)}
                        style={{ width: columnWidths[colName] || '150px' }}
                      >
                        <div className="dvm-th-content">
                          <span>{colName}</span>
                          {isActive && (
                            <span className="dvm-sort-icon">
                              {sortAsce ? '↑' : '↓'}
                            </span>
                          )}
                        </div>
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {paginatedData.length > 0 ? (
                  paginatedData.map((row, rowIdx) => (
                    <tr key={rowIdx} className={rowIdx % 2 === 0 ? 'even' : 'odd'}>
                      {displayColumns.map((col) => {
                        const colName = col.name || col;
                        const val = row[colName];
                        return (
                          <td
                            key={`${rowIdx}-${colName}`}
                            className="dvm-td"
                            style={{ width: columnWidths[colName] || '150px' }}
                            title={String(val)}
                          >
                            {val === null || val === undefined || val === '' ? (
                              <span className="dvm-null">null</span>
                            ) : (
                              String(val).substring(0, 100)
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={displayColumns.length} className="dvm-no-data">
                      No data matches your search.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination & Info */}
          <div className="dvm-footer">
            <span className="dvm-info">
              Showing {paginatedData.length > 0 ? currentPage * ROWS_PER_PAGE + 1 : 0}
              {' '}-{' '}
              {Math.min((currentPage + 1) * ROWS_PER_PAGE, sortedData.length)}
              {' '}of {sortedData.length} rows
              {searchTerm && ` (filtered from ${data.length})`}
            </span>
            
            <div className="dvm-pagination">
              <button
                className="dvm-pagination-btn"
                onClick={() => setCurrentPage(Math.max(0, currentPage - 1))}
                disabled={currentPage === 0}
              >
                ← Prev
              </button>

              <span className="dvm-page-info">
                Page {currentPage + 1} / {totalPages}
              </span>

              <button
                className="dvm-pagination-btn"
                onClick={() => setCurrentPage(Math.min(totalPages - 1, currentPage + 1))}
                disabled={currentPage >= totalPages - 1}
              >
                Next →
              </button>
            </div>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}

export default DataViewerModal;
