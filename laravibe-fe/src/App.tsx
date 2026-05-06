import { useState, useEffect } from 'react';
import { Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { motion, AnimatePresence } from 'motion/react';
import { Layout } from './components/Layout';
import { AnalyzerView } from './components/AnalyzerView';
import { RepairView } from './components/RepairView';
import { HistoryView } from './components/HistoryView';
import { IterationView } from './components/IterationView';
import { TestsView } from './components/TestsView';
import { ShortcutsModal } from './components/ShortcutsModal';
import { AdminDashboardView } from './components/AdminDashboardView';
import { LoginView } from './components/LoginView';
import { RepairsListView } from './components/RepairsListView';
import { ReportsView } from './components/ReportsView';

/**
 * Auth model:
 * - Session token (JWT) is stored in localStorage as 'laravibe_session_token'
 * - It is set after the LoginView exchanges the master key for a JWT via POST /api/auth/login
 * - The master key itself is NEVER stored here or in the bundle
 * - Logging out clears the session token
 */
const SESSION_KEY = 'laravibe_session_token';

export default function App() {
  const [isShortcutsOpen, setIsShortcutsOpen] = useState(false);
  const [sessionToken, setSessionToken] = useState<string | null>(
    () => localStorage.getItem(SESSION_KEY)
  );
  const [theme, setTheme] = useState<'light' | 'dark'>(
    () => (localStorage.getItem('laravibe_theme') as 'light' | 'dark') || 'dark'
  );
  const location = useLocation();

  const handleLogin = (token: string) => {
    // token is a JWT issued by /api/auth/login — not the raw master key
    localStorage.setItem(SESSION_KEY, token);
    setSessionToken(token);
  };

  const handleSignOut = () => {
    localStorage.removeItem(SESSION_KEY);
    window.location.href = '/';
  };

  // Listen for '?' key to open shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === '?' && !isShortcutsOpen) setIsShortcutsOpen(true);
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isShortcutsOpen]);

  // Handle theme persistence
  useEffect(() => {
    const root = window.document.documentElement;
    if (theme === 'dark') {
      root.classList.add('dark');
      root.classList.remove('light');
    } else {
      root.classList.add('light');
      root.classList.remove('dark');
    }
    localStorage.setItem('laravibe_theme', theme);
  }, [theme]);

  // Gate: show login screen if no session token
  if (!sessionToken) {
    return <LoginView onLogin={handleLogin} />;
  }

  return (
    <Layout
      theme={theme}
      onThemeToggle={() => setTheme(prev => prev === 'dark' ? 'light' : 'dark')}
      onSignOut={handleSignOut}
    >
      <AnimatePresence mode="wait">
        <motion.div
          key={location.pathname}
          initial={{ opacity: 0, scale: 0.98 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 1.02 }}
          transition={{ duration: 0.2, ease: 'easeOut' }}
          className="flex-1 flex overflow-hidden"
        >
          <Routes location={location}>
            <Route path="/" element={<Navigate to="/analyzer" replace />} />
            <Route path="/analyzer" element={<AnalyzerView />} />
            <Route path="/repair/:submissionId" element={<RepairView />} />
            <Route path="/history" element={<HistoryView />} />
            <Route path="/iteration/:submissionId" element={<IterationView />} />
            <Route path="/tests/:submissionId" element={<TestsView />} />
            <Route path="/admin" element={<AdminDashboardView />} />
            <Route path="/repairs" element={<RepairsListView />} />
            <Route path="/reports" element={<ReportsView />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </motion.div>
      </AnimatePresence>

      <ShortcutsModal
        isOpen={isShortcutsOpen}
        onClose={() => setIsShortcutsOpen(false)}
      />
    </Layout>
  );
}
