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

export default function App() {
  const [isShortcutsOpen, setIsShortcutsOpen] = useState(false);
  const [theme, setTheme] = useState<'light' | 'dark'>('dark');
  const location = useLocation();

  // Listen for '?' key to open shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === '?' && !isShortcutsOpen) {
        setIsShortcutsOpen(true);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isShortcutsOpen]);

  // Apply theme to document
  useEffect(() => {
    const root = window.document.documentElement;
    if (theme === 'dark') {
      root.classList.add('dark');
      root.classList.remove('light');
    } else {
      root.classList.add('light');
      root.classList.remove('dark');
    }
  }, [theme]);

  const toggleTheme = () => {
    setTheme(prev => prev === 'dark' ? 'light' : 'dark');
  };

  return (
    <Layout 
      theme={theme}
      onThemeToggle={toggleTheme}
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
          <Routes location={location} key={location.pathname}>
            <Route path="/" element={<AnalyzerView />} />
            <Route path="/repair/:submissionId" element={<RepairView />} />
            <Route path="/history" element={<HistoryView />} />
            <Route path="/iteration/:submissionId" element={<IterationView />} />
            <Route path="/tests/:submissionId" element={<TestsView />} />
            <Route path="/admin" element={<AdminDashboardView />} />
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
