/**
 * StatsFlow Entry Point
 * Fixes React Router v7 future flag warnings.
 */

import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { Toaster } from 'react-hot-toast';
import App from './App';
import { DataProvider } from './context/DataContext';
import './styles/global.css';

const root = ReactDOM.createRoot(document.getElementById('root'));

root.render(
  <React.StrictMode>
    {/* Future flags silence the React Router v6 → v7 warnings */}
    <BrowserRouter
      future={{
        v7_startTransition:   true,
        v7_relativeSplatPath: true,
      }}
    >
      <DataProvider>
        <App />
        <Toaster
          position="top-right"
          toastOptions={{
            duration: 4000,
            style: {
              fontFamily:   'Inter, sans-serif',
              fontSize:     '0.875rem',
              borderRadius: '12px',
              boxShadow:    '0 4px 20px rgba(0,0,0,0.12)',
            },
            success: {
              iconTheme: { primary: '#10b981', secondary: '#fff' },
            },
            error: {
              iconTheme: { primary: '#ef4444', secondary: '#fff' },
            },
          }}
        />
      </DataProvider>
    </BrowserRouter>
  </React.StrictMode>
);