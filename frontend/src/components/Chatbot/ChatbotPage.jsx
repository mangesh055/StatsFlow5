/**
 * StatsFlow Chatbot Page — Phase 4
 * -----------------------------------
 * Agentic AI chatbot with full dataset context.
 * Supports both Q&A and data manipulation commands.
 */

import React, { useState, useRef, useEffect } from 'react';
import { motion } from 'framer-motion';
import toast from 'react-hot-toast';
import { useData } from '../../context/DataContext';
import { sendChatMessage, downloadCleanedDataset, getChatHistory } from '../../api/api';
import ChatMessage from './ChatMessage';
import DataViewerModal from './DataViewerModal';
import './Chatbot.css';

const SAMPLE_QUESTIONS = [
  'What are the top 5 insights from this dataset?',
  'Which columns have the highest correlation?',
  'What is the average of all numeric columns?',
  'Drop all rows where the age column is empty',
  'What is the distribution of the target column?',
  'Are there any remaining outliers after cleaning?',
];

function ChatbotPage() {
  const { sessionId, messages, addMessage, updateState, cleanedShape, filename } = useData();
  const [input, setInput] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [manipulatedPreview, setManipulatedPreview] = useState([]);
  const [manipulationColumns, setManipulationColumns] = useState([]);
  const [manipulationPage, setManipulationPage] = useState(0);
  const [lastAction, setLastAction] = useState(null);
  const [chatThreads, setChatThreads] = useState([]);
  const [currentThreadId, setCurrentThreadId] = useState('default');
  const [isThreadsLoaded, setIsThreadsLoaded] = useState(false);
  const [showDataViewer, setShowDataViewer] = useState(false);
  const [showDataPanel, setShowDataPanel] = useState(true);
  
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);

  const CHAT_TABLE_PAGE_SIZE = 8;

  // Auto-scroll to latest message
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Load chat history on mount
  useEffect(() => {
    if (sessionId && !isThreadsLoaded) {
      getChatHistory(sessionId).then(data => {
        if (data.success && data.threads) {
          setChatThreads(data.threads);
          setIsThreadsLoaded(true);
          
          if (data.threads.length > 0) {
            const activeThread = data.threads[data.threads.length - 1];
            setCurrentThreadId(activeThread.thread_id);
            
            const loadedMessages = (activeThread.messages || []).map((m, i) => ({
              id: Date.now() + i, // Generate fallback IDs
              role: m.role,
              content: m.content,
              action: m.action || null,
              meta: m.meta || null,
              timestamp: m.timestamp || new Date().toISOString()
            }));
            updateState({ messages: loadedMessages });
          }
        }
      }).catch(err => {
        console.error("Failed to load chat history", err);
      });
    }
  }, [sessionId, isThreadsLoaded, updateState]);

  const handleNewChat = () => {
    const newThreadId = 'thread_' + Date.now().toString();
    const newThread = {
      thread_id: newThreadId,
      title: 'New Chat',
      messages: []
    };
    setChatThreads([newThread, ...chatThreads]);
    setCurrentThreadId(newThreadId);
    updateState({ messages: [] });
    setManipulatedPreview([]);
    setLastAction(null);
  };

  const handleSwitchThread = (thread) => {
    if (thread.thread_id === currentThreadId) return;
    
    setCurrentThreadId(thread.thread_id);
    const loadedMessages = (thread.messages || []).map((m, i) => ({
      id: Date.now() + i,
      role: m.role,
      content: m.content,
      action: m.action || null,
      meta: m.meta || null,
      timestamp: m.timestamp || new Date().toISOString()
    }));
    updateState({ messages: loadedMessages });
    
    setManipulatedPreview([]);
    setLastAction(null);
  };

  const handleSend = async (messageText = null) => {
    const text = (messageText || input).trim();
    if (!text || isSending) return;

    setInput('');
    setIsSending(true);

    // Optimistically add user message
    addMessage('user', text);

    try {
      const data = await sendChatMessage(sessionId, text, messages, currentThreadId);

      addMessage('assistant', data.response, data.action_performed, data.response_meta || null);

      // If this is the first message in a new thread, refresh threads to get the AI-generated title
      if (messages.length === 0) {
        getChatHistory(sessionId).then(res => {
          if (res.success && res.threads) setChatThreads(res.threads);
        });
      }

      if (data.action_performed) {
        toast.success(`✅ Action executed: ${data.action_performed.operation?.replace(/_/g, ' ')}`);
      }

      if (data.updated_shape) {
        updateState({
          cleanedShape: data.updated_shape,
          qualityScorecard: data.quality_scorecard ? { cleaned: data.quality_scorecard } : null,
          anomalyReport: data.anomaly_report || null,
        });
      }

      if (data.action_performed && data.cleaned_preview) {
        setManipulatedPreview(data.cleaned_preview || []);
        setManipulationColumns(data.columns_info || []);
        setManipulationPage(0);
        setLastAction(data.action_performed);

        if (data.cleaned_shape || data.updated_shape) {
          updateState({
            cleanedShape: data.cleaned_shape || data.updated_shape || cleanedShape,
          });
        }
      }
    } catch (err) {
      const errMsg = err.response?.data?.detail || 'Network error. Please try again.';
      addMessage('assistant', `⚠️ Error: ${errMsg}`, null, null);
      toast.error(errMsg);
    } finally {
      setIsSending(false);
      inputRef.current?.focus();
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const chatColumns = Object.keys(manipulatedPreview[0] || {});
  const chatTotalPages = Math.max(1, Math.ceil(manipulatedPreview.length / CHAT_TABLE_PAGE_SIZE));
  const chatPageData = manipulatedPreview.slice(
    manipulationPage * CHAT_TABLE_PAGE_SIZE,
    (manipulationPage + 1) * CHAT_TABLE_PAGE_SIZE
  );

  const getTypeBadge = (colName) => {
    const info = manipulationColumns?.find(c => c.name === colName);
    const type = info?.type || 'categorical';
    if (type === 'numeric') return 'NUM';
    if (type === 'datetime') return 'DT';
    return 'CAT';
  };

  const formatCell = (val) => {
    if (val === null || val === undefined || val === '') return '—';
    if (typeof val === 'number') return Number.isInteger(val) ? val : val.toFixed(4);
    return String(val);
  };

  return (
    <div className="chat-page">
      {/* ── Sidebar ─────────────────────────────────────────── */}
      <div className="chat-sidebar">
        <div className="chat-sidebar-header">
          <div className="chat-sidebar-logo">🤖</div>
          <div>
            <div className="chat-sidebar-title">AI Data Analyst</div>
            <div className="chat-sidebar-status">
              <span className="chat-online-dot" /> Online
            </div>
          </div>
        </div>

        {/* Dataset Info */}
        <div className="chat-dataset-info">
          <div className="chat-dataset-title">📊 Active Dataset</div>
          <div className="chat-dataset-name">{filename}</div>
          <div className="chat-dataset-shape">
            {cleanedShape?.rows?.toLocaleString()} rows ×{' '}
            {cleanedShape?.columns} columns
          </div>
          <div className="chat-dataset-actions">
            <button
              className="chat-action-btn"
              onClick={() => downloadCleanedDataset(sessionId, `${filename.split('.')[0]}_cleaned.csv`)}
              title="Download cleaned dataset as CSV"
            >
              📥 Download
            </button>
            <button
              className="chat-action-btn"
              onClick={() => setShowDataViewer(true)}
              title="View data in fullscreen"
            >
              🗂️ Fullscreen
            </button>
          </div>
        </div>

        {/* New Chat button */}
        <button className="chat-new-chat-btn" onClick={handleNewChat}>
          <span style={{ fontSize: '1.1rem' }}>✏️</span> New Chat
        </button>

        <div className="chat-sidebar-section">
          <div className="chat-sidebar-section-title">Recent Chats</div>
          <div className="chat-recent-list">
            {chatThreads.length === 0 ? (
              <div className="chat-recent-empty">No conversations yet</div>
            ) : (
              [...chatThreads].reverse().map((t) => (
                <button
                  key={t.thread_id}
                  className={`chat-recent-item ${t.thread_id === currentThreadId ? 'active' : ''}`}
                  onClick={() => handleSwitchThread(t)}
                  title={t.title}
                >
                  <span className="icon">💬</span>
                  <span className="chat-recent-item-title">{t.title || 'Conversation'}</span>
                </button>
              ))
            )}
          </div>
        </div>

        {/* Capabilities */}
        <div className="chat-capabilities">
          <div className="chat-capabilities-title">⚡ Capabilities</div>
          <div className="chat-capability">📊 Statistical analysis</div>
          <div className="chat-capability">🔗 Correlation queries</div>
          <div className="chat-capability">🧹 Drop rows/columns</div>
          <div className="chat-capability">📝 Rename & filter</div>
          <div className="chat-capability">🔢 Fill missing values</div>
        </div>
      </div>

      {/* ── Main Chat Area ───────────────────────────────────── */}
      <div className="chat-main">
        {/* Header */}
        <div className="chat-main-header">
          <h2 className="chat-main-title">StatsFlow AI Analyst</h2>
          <span className="badge badge-success">Context-Aware</span>
        </div>

        <div className="chat-main-body">
          <div className="chat-conversation-column">
            {/* Messages */}
            <div className="chat-messages">
              {/* Welcome Message */}
              {messages.length === 0 && (
                <motion.div
                  className="chat-welcome"
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                >
                  <div className="chat-welcome-icon">🤖</div>
                  <h3>Hello! I'm your AI Data Analyst.</h3>
                  <p>
                    I have full context of your cleaned dataset
                    <strong> ({filename})</strong>. Ask me any question about your
                    data, or tell me to perform operations like dropping rows or
                    filtering columns.
                  </p>
                </motion.div>
              )}

              {/* Message List */}
              {messages.map((msg, i) => (
                <motion.div
                  key={msg.id}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.05 }}
                >
                  <ChatMessage message={msg} onFollowUp={handleSend} />
                </motion.div>
              ))}

              {/* Typing Indicator */}
              {isSending && (
                <motion.div
                  className="chat-typing"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                >
                  <div className="chat-avatar">🤖</div>
                  <div className="chat-typing-bubble">
                    <span /><span /><span />
                  </div>
                </motion.div>
              )}

              <div ref={messagesEndRef} />
            </div>

            {/* Input Area */}
            <div className="chat-input-area">
              <div className="chat-input-wrapper">
                <textarea
                  ref={inputRef}
                  className="chat-input"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Ask a question or give a command... (Shift+Enter for new line)"
                  rows={1}
                  disabled={isSending}
                />
                <button
                  className="chat-send-btn"
                  onClick={() => handleSend()}
                  disabled={!input.trim() || isSending}
                >
                  {isSending ? <div className="spinner" /> : '▶'}
                </button>
              </div>
              <p className="chat-input-hint">
                ⌨️ Press Enter to send • Shift+Enter for new line
              </p>
            </div>
          </div>

          {/* Show-panel tab when collapsed */}
          {!showDataPanel && (
            <button
              className="chat-panel-show-tab"
              onClick={() => setShowDataPanel(true)}
              title="Show Dataset Manipulation View"
            >
              ◀ Data
            </button>
          )}

          <div className={`chat-manipulation-panel ${showDataPanel ? '' : 'chat-panel-hidden'}`}>
            <div className="chat-manipulation-header">
              <h3>Dataset Manipulation View</h3>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span className="badge badge-primary">
                  {manipulatedPreview.length > 0 ? `${manipulatedPreview.length} rows` : 'No edits yet'}
                </span>
                <button
                  className="chat-panel-toggle-btn"
                  onClick={() => setShowDataPanel(p => !p)}
                  title="Hide panel"
                >
                  ⟩
                </button>
              </div>
            </div>

            {lastAction && (
              <div className="chat-manipulation-action">
                <strong>Last Action:</strong> {lastAction.operation?.replace(/_/g, ' ')}
                {lastAction.result ? ` — ${lastAction.result}` : ''}
              </div>
            )}

            {manipulatedPreview.length === 0 ? (
              <div className="chat-manipulation-empty">
                Run a chat command like drop, rename, replace, or update to view manipulated data here.
              </div>
            ) : (
              <>
                <div className="chat-manipulation-table-wrap">
                  <table className="chat-manipulation-table">
                    <thead>
                      <tr>
                        {chatColumns.map((col) => (
                          <th key={col}>
                            <div className="chat-col-header">
                              <span>{col}</span>
                              <span className="chat-col-badge">{getTypeBadge(col)}</span>
                            </div>
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {chatPageData.map((row, idx) => (
                        <tr key={idx}>
                          {chatColumns.map((col) => (
                            <td key={col}>{formatCell(row[col])}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {chatTotalPages > 1 && (
                  <div className="chat-table-pagination">
                    <button
                      className="btn btn-secondary"
                      onClick={() => setManipulationPage((p) => Math.max(0, p - 1))}
                      disabled={manipulationPage === 0}
                    >
                      ← Prev
                    </button>
                    <span>Page {manipulationPage + 1} of {chatTotalPages}</span>
                    <button
                      className="btn btn-secondary"
                      onClick={() => setManipulationPage((p) => Math.min(chatTotalPages - 1, p + 1))}
                      disabled={manipulationPage >= chatTotalPages - 1}
                    >
                      Next →
                    </button>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>

      {/* Data Viewer Modal */}
      <DataViewerModal
        isOpen={showDataViewer}
        data={manipulatedPreview.length > 0 ? manipulatedPreview : []}
        columns={manipulationColumns}
        title={manipulatedPreview.length > 0 ? 'Manipulated Data' : 'Cleaned Data'}
        onClose={() => setShowDataViewer(false)}
      />
    </div>
  );
}

export default ChatbotPage;