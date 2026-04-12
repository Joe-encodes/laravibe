import React from 'react';
import { 
  Brain, Settings, Terminal, Network, Code, Bug, HelpCircle, 
  MessageSquare, History, List, Diff, CheckCircle2, Github,
  Activity, Cpu, ChevronUp, Sun, Moon
} from 'lucide-react';
import { useNavigate, useLocation } from 'react-router-dom';
import { cn } from '../lib/utils';
import { View } from '../types';

interface LayoutProps {
  children: React.ReactNode;
  theme: 'light' | 'dark';
  onThemeToggle: () => void;
}

export const Layout: React.FC<LayoutProps> = ({ children, theme, onThemeToggle }) => {
  const navigate = useNavigate();
  const location = useLocation();

  const isPathActive = (path: string) => {
    if (path === '/' && location.pathname === '/') return true;
    if (path !== '/' && location.pathname.startsWith(path)) return true;
    return false;
  };

  // Extract submissionId from URL for contextual navigation
  const submissionIdMatch = location.pathname.match(/\/(repair|iteration|tests)\/([^\/]+)/);
  const submissionId = submissionIdMatch ? submissionIdMatch[2] : localStorage.getItem('last_submission_id');

  // Persist submissionId if we are on a relevant page
  React.useEffect(() => {
    const match = location.pathname.match(/\/(repair|iteration|tests)\/([^\/]+)/);
    if (match && match[2] !== 'latest') {
      localStorage.setItem('last_submission_id', match[2]);
    }
  }, [location.pathname]);

  return (
    <div className="h-screen flex flex-col overflow-hidden bg-surface-container-lowest text-on-surface transition-colors duration-300">
      {/* TopAppBar */}
      <header className="bg-machined-header flex justify-between items-center w-full px-4 h-14 border-b border-machined-border font-mono tracking-tight z-50">
        <div className="flex items-center gap-6">
          <span className="text-xl font-bold tracking-tighter text-indigo-400 uppercase">LARAVIBE</span>
          <span className="text-machined-text-dim text-xs font-bold px-2 py-0.5 bg-machined-header border border-machined-border rounded">v1.0</span>
        </div>
        
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2 bg-machined-header px-3 py-1 border border-machined-border">
            <span className="w-2 h-2 rounded-full bg-secondary"></span>
            <span className="text-[10px] font-bold text-secondary uppercase tracking-widest">API Connected</span>
          </div>
          <div className="flex items-center gap-2 bg-indigo-950/30 dark:bg-indigo-950/30 px-3 py-1 border border-indigo-900/50">
            <Brain className="text-indigo-400 w-4 h-4" />
            <span className="text-[10px] font-bold text-indigo-400 uppercase tracking-widest">Claude Sonnet 4.6</span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button 
            onClick={onThemeToggle}
            className="p-2 text-machined-text-dim hover:bg-surface-container-high transition-colors rounded-lg"
            title={theme === 'dark' ? 'Switch to Light Mode' : 'Switch to Dark Mode'}
          >
            {theme === 'dark' ? <Sun className="w-5 h-5" /> : <Moon className="w-5 h-5" />}
          </button>
          {/* Removed non-functional header buttons */}
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* SideNavBar */}
        <aside className="flex flex-col h-full items-center py-4 bg-machined-sidebar border-r border-machined-border w-16 flex-shrink-0">
          <nav className="flex flex-col gap-4 w-full items-center">
            <button 
              onClick={() => navigate('/')}
              className={cn(
                "w-10 h-10 flex items-center justify-center transition-all duration-150 cursor-pointer",
                isPathActive('/') && location.pathname === '/' ? "text-indigo-400 border-l-2 border-indigo-400 bg-surface-container" : "text-machined-text-dim hover:text-on-surface hover:bg-surface-container"
              )}
            >
              <Code className="w-5 h-5" />
            </button>
            <button 
              onClick={() => navigate(submissionId ? `/repair/${submissionId}` : '/')}
              className={cn(
                "w-10 h-10 flex items-center justify-center transition-all duration-150 cursor-pointer",
                isPathActive('/repair') ? "text-indigo-400 border-l-2 border-indigo-400 bg-surface-container" : "text-machined-text-dim hover:text-on-surface hover:bg-surface-container"
              )}
            >
              <Bug className="w-5 h-5" />
            </button>
            <button 
              onClick={() => navigate('/history')}
              className={cn(
                "w-10 h-10 flex items-center justify-center transition-all duration-150 cursor-pointer",
                isPathActive('/history') ? "text-indigo-400 border-l-2 border-indigo-400 bg-surface-container" : "text-machined-text-dim hover:text-on-surface hover:bg-surface-container"
              )}
            >
              <History className="w-5 h-5" />
            </button>
            <button 
              onClick={() => navigate('/admin')}
              className={cn(
                "w-10 h-10 flex items-center justify-center transition-all duration-150 cursor-pointer",
                isPathActive('/admin') ? "text-error border-l-2 border-error bg-surface-container" : "text-machined-text-dim hover:text-error hover:bg-surface-container"
              )}
              title="Admin Dashboard"
            >
              <Settings className="w-5 h-5" />
            </button>
          </nav>
          <div className="mt-auto flex flex-col gap-4 w-full items-center px-1 pb-2">
            <button 
              onClick={() => navigate('/')}
              className={cn(
                "w-full py-2.5 font-mono text-[10px] leading-tight font-bold uppercase tracking-tighter rounded-md transition-all active:scale-95 border text-center flex flex-col items-center justify-center gap-1",
                isPathActive('/') && location.pathname === '/' 
                  ? "bg-primary text-on-primary border-primary shadow-[0_0_15px_rgba(99,102,241,0.3)]" 
                  : "bg-primary-container text-on-primary-container border-outline-variant hover:brightness-110"
              )}
            >
              <span>RUN</span>
              <span>DIAGNOSTICS</span>
            </button>
          </div>
        </aside>

        {/* Main Content */}
        <main className="flex-1 flex overflow-hidden bg-surface-container-lowest">
          {children}
        </main>
      </div>

      {/* BottomNavBar */}
      <footer className="h-12 bg-machined-footer border-t border-machined-border flex justify-between items-center px-4 z-50">
        <div className="flex items-center gap-6">
          <button 
            onClick={() => navigate('/history')}
            className={cn(
              "flex items-center gap-2 group",
              isPathActive('/history') ? "opacity-100" : "opacity-60 hover:opacity-100"
            )}
          >
            <History className="w-4 h-4 text-emerald-400 group-hover:scale-110 transition-transform" />
            <span className="mono text-[10px] uppercase font-bold text-machined-text-dim group-hover:text-emerald-400 transition-colors">HISTORY</span>
          </button>
          <div className="h-4 w-px bg-machined-border"></div>
          <div className="flex items-center gap-4">
            <button 
              onClick={() => submissionId && navigate(`/repair/${submissionId}`)}
              className={cn(
                "flex items-center gap-2 transition-all",
                submissionId ? (isPathActive('/repair') ? "opacity-100" : "opacity-60 hover:opacity-100") : "opacity-30 cursor-not-allowed"
              )}
              disabled={!submissionId}
            >
              <List className="w-4 h-4 text-machined-text-dim" />
              <span className="mono text-[10px] text-machined-text-dim font-bold uppercase">LOGS</span>
            </button>
            <button 
              onClick={() => submissionId && navigate(`/iteration/${submissionId}`)}
              className={cn(
                "flex items-center gap-2 transition-all",
                submissionId ? (isPathActive('/iteration') ? "opacity-100" : "opacity-60 hover:opacity-100") : "opacity-30 cursor-not-allowed"
              )}
              disabled={!submissionId}
            >
              <Diff className="w-4 h-4 text-machined-text-dim" />
              <span className="mono text-[10px] text-machined-text-dim font-bold uppercase">DIFF</span>
            </button>
            <button 
              onClick={() => submissionId && navigate(`/tests/${submissionId}`)}
              className={cn(
                "flex items-center gap-2 transition-all",
                submissionId ? (isPathActive('/tests') ? "opacity-100" : "opacity-60 hover:opacity-100") : "opacity-30 cursor-not-allowed"
              )}
              disabled={!submissionId}
            >
              <CheckCircle2 className="w-4 h-4 text-machined-text-dim" />
              <span className="mono text-[10px] text-machined-text-dim font-bold uppercase">TESTS</span>
            </button>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span className="mono text-[9px] text-machined-text-dim font-bold tracking-widest uppercase">STATUS: {isPathActive('/repair') ? 'REPAIRING' : 'WAITING'}</span>
        </div>
      </footer>
    </div>
  );
};
