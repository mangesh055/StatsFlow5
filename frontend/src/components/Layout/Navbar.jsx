/**
 * StatsFlow Navigation Bar
 * --------------------------
 * Displays the brand, pipeline progress steps, and navigation links.
 * Steps are disabled until the user has completed the prerequisite phases.
 */

import React from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useData } from '../../context/DataContext';
import './Layout.css';

const STEPS = [
  { label: 'Upload',     path: '/upload',    icon: '📁', minStep: 0 },
  { label: 'Clean',      path: '/dashboard', icon: '🧹', minStep: 1 },
  { label: 'Visualize',  path: '/visualize', icon: '📊', minStep: 2 },
  { label: 'Chat',       path: '/chat',      icon: '🤖', minStep: 2 },
];

function Navbar() {
  const { currentStep, filename, resetAll, theme, toggleTheme } = useData();
  const navigate = useNavigate();
  const location = useLocation();

  const handleStepClick = (step) => {
    if (currentStep >= step.minStep) {
      navigate(step.path);
    }
  };

  const handleReset = () => {
    if (window.confirm('Start over? All current session data will be cleared.')) {
      resetAll();
      navigate('/');
    }
  };

  return (
    <nav className="navbar">
      {/* Brand */}
      <div className="navbar-brand" onClick={() => navigate('/')}>
        <div className="navbar-logo">
          <span className="navbar-logo-icon">⚡</span>
        </div>
        <div>
          <div className="navbar-title">StatsFlow</div>
          <div className="navbar-subtitle">AI Data Processing Platform</div>
        </div>
      </div>

      {/* Pipeline Steps */}
      <div className="navbar-steps">
        {STEPS.map((step, idx) => {
          const isActive    = location.pathname === step.path;
          const isCompleted = currentStep > step.minStep;
          const isAccessible = currentStep >= step.minStep;

          return (
            <button
              key={step.path}
              className={[
                'navbar-step',
                isActive    ? 'navbar-step--active'    : '',
                isCompleted ? 'navbar-step--completed' : '',
                !isAccessible ? 'navbar-step--locked' : '',
              ].join(' ')}
              onClick={() => handleStepClick(step)}
              disabled={!isAccessible}
              title={!isAccessible ? `Complete previous step first` : step.label}
            >
              <span className="navbar-step-icon">
                {isCompleted && !isActive ? '✅' : step.icon}
              </span>
              <span className="navbar-step-label">{step.label}</span>
              {idx < STEPS.length - 1 && (
                <span className="navbar-step-arrow">›</span>
              )}
            </button>
          );
        })}
      </div>

      {/* Right Side */}
      <div className="navbar-right">
        <button
          className="btn btn-secondary navbar-theme-btn"
          onClick={toggleTheme}
          title={`Switch to ${theme === 'light' ? 'dark' : 'light'} theme`}
        >
          {theme === 'light' ? 'Dark Mode' : 'Light Mode'}
        </button>
        {filename && (
          <div className="navbar-file-badge">
            <span>📄</span>
            <span className="navbar-filename">
              {filename.length > 20 ? filename.slice(0, 18) + '...' : filename}
            </span>
          </div>
        )}
        {currentStep > 0 && (
          <button className="btn btn-secondary navbar-reset-btn" onClick={handleReset}>
            ↺ Reset
          </button>
        )}
      </div>
    </nav>
  );
}

export default Navbar;