/**
 * StatsFlow App Router
 * ---------------------
 * Fixes React Router v6 future flag warnings.
 * Enforces the 4-step linear workflow with route guards.
 */

// new changes
import React, { useEffect, useRef } from 'react';
import { Routes, Route, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { useData } from './context/DataContext';
import Navbar from './components/Layout/Navbar';
import HomePage from './components/Home/HomePage';
import UploadPage from './components/Upload/UploadPage';
import Dashboard from './components/Dashboard/Dashboard';
import VisualizationPage from './components/Visualizations/VisualizationPage';
import ChatbotPage from './components/Chatbot/ChatbotPage';

/**
 * Guard component — redirects to the correct step
 * if the user tries to jump ahead in the workflow.
 */
function GuardedRoute({ children, requiredStep, currentStep }) {
  if (currentStep < requiredStep) {
    const redirectPaths = ['/', '/dashboard', '/visualize', '/chat'];
    const safePath = redirectPaths[currentStep] || '/';
    return <Navigate to={safePath} replace />;
  }
  return children;
}

function App() {
  const { currentStep } = useData();
  const location = useLocation();
  const navigate = useNavigate();
  const previousPathRef = useRef(location.pathname);
  const suppressPromptRef = useRef(false);

  useEffect(() => {
    const previousPath = previousPathRef.current;

    if (suppressPromptRef.current) {
      suppressPromptRef.current = false;
      previousPathRef.current = location.pathname;
      return;
    }

    const movingBackToUpload = previousPath !== '/' && previousPath !== '/upload' && (location.pathname === '/' || location.pathname === '/upload');
    const hasProgress = currentStep > 0;

    if (movingBackToUpload && hasProgress) {
      const confirmed = window.confirm(
        'You have uploaded data and progress in this session. Do you really want to go back to Upload?'
      );

      if (!confirmed) {
        suppressPromptRef.current = true;
        navigate(previousPath, { replace: true });
        return;
      }
    }

    previousPathRef.current = location.pathname;
  }, [location.pathname, currentStep, navigate]);

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <Navbar />
      <main style={{ flex: 1 }}>
        <Routes>
          {/* Home — Power BI-style Start Screen (always accessible) */}
          <Route path="/" element={<HomePage />} />

          {/* Phase 1 — Upload (direct URL fallback) */}
          <Route path="/upload" element={<UploadPage />} />

          {/* Phase 2 — Dashboard & Cleaning */}
          <Route
            path="/dashboard"
            element={
              <GuardedRoute requiredStep={1} currentStep={currentStep}>
                <Dashboard />
              </GuardedRoute>
            }
          />

          {/* Phase 3 — Visualizations */}
          <Route
            path="/visualize"
            element={
              <GuardedRoute requiredStep={2} currentStep={currentStep}>
                <VisualizationPage />
              </GuardedRoute>
            }
          />

          {/* Phase 4 — AI Chatbot */}
          <Route
            path="/chat"
            element={
              <GuardedRoute requiredStep={2} currentStep={currentStep}>
                <ChatbotPage />
              </GuardedRoute>
            }
          />

          {/* Catch-all redirect */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}

export default App;