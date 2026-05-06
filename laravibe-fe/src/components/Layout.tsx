import React from 'react';
import { 
  Code, 
  Bug, 
  History, 
  Settings, 
  List, 
  Diff, 
  CheckCircle2, 
  ShieldAlert,
  Sun,
  Moon,
  LogOut,
  Brain,
  Activity,
  BarChart2
} from 'lucide-react';
import { useNavigate, useLocation } from 'react-router-dom';
import { cn } from '../lib/utils';

interface LayoutProps {
  children: React.ReactNode;
  theme: 'light' | 'dark';
  onThemeToggle: () => void;
  onSignOut: () => void;
}

export const Layout: React.FC<LayoutProps> = ({ children, theme, onThemeToggle, onSignOut }) => {
  const navigate = useNavigate();
  const location = useLocation();

  const isPathActive = (path: string) => {
    if (path === '/' && location.pathname === '/') return true;
    if (path !== '/' && location.pathname.startsWith(path)) return true;
    return false;
  };

  const submissionIdMatch = location.pathname.match(/\/(repair|iteration|tests)\/([^\/]+)/);
  const submissionId = submissionIdMatch ? submissionIdMatch[2] : localStorage.getItem('last_submission_id');

  React.useEffect(() => {
    const match = location.pathname.match(/\/(repair|iteration|tests)\/([^\/]+)/);
    if (match && match[2] !== 'latest') {
      localStorage.setItem('last_submission_id', match[2]);
    }
  }, [location.pathname]);

  const navLinks = [
    { path: '/', icon: Code, title: 'Analyzer workspace' },
    { path: '/repair', icon: Bug, title: 'Active repair stream', useId: true },
    { path: '/history', icon: History, title: 'Repair history' },
    { path: '/repairs', icon: Activity, title: 'Active nodes' },
    { path: '/reports', icon: BarChart2, title: 'Analytics reports' },
    { path: '/admin', icon: ShieldAlert, title: 'Admin dashboard', admin: true },
  ];

  return (
    <div className="h-screen flex flex-col overflow-hidden bg-surface-container-lowest text-on-surface transition-colors duration-300">
      {/* TopAppBar */}
      <header className="bg-machined-header flex justify-between items-center w-full px-4 h-14 border-b border-machined-border font-mono z-50 shrink-0">
        <div className="flex items-center gap-4">
          <span className="text-lg font-semibold tracking-tight text-indigo-400">Laravibe</span>
          <span className="text-machined-text-dim text-[11px] font-medium px-2 py-0.5 bg-machined-header border border-machined-border rounded hidden sm:inline-block">v1.0</span>
        </div>
        
        <div className="flex items-center gap-2 md:gap-3 overflow-x-auto no-scrollbar">
          <div className="hidden sm:flex items-center gap-2 rounded-full bg-machined-header/70 px-3 py-1 border border-machined-border text-sm text-on-surface-variant">
            <span className="w-2 h-2 rounded-full bg-secondary" />
            <span className="font-medium text-secondary whitespace-nowrap">API connected</span>
          </div>
          <div className="flex items-center gap-2 rounded-full bg-primary/10 px-3 py-1 border border-primary/20 text-sm text-primary shrink-0">
            <Brain className="w-4 h-4 shrink-0" />
            <span className="font-bold uppercase tracking-widest text-[10px] whitespace-nowrap">Multi-agent cluster</span>
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0 ml-2">
          <button 
            onClick={onSignOut}
            className="p-2 text-machined-text-dim hover:text-error hover:bg-error/10 transition-all rounded-lg"
            title="Sign Out"
          >
            <LogOut className="w-5 h-5" />
          </button>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden flex-col md:flex-row">
        {/* SideNavBar (Desktop) */}
        <aside className="hidden md:flex flex-col h-full items-center py-4 bg-machined-sidebar border-r border-machined-border w-16 flex-shrink-0">
          <nav className="flex flex-col gap-4 w-full items-center">
            {navLinks.map((link, i) => {
              const active = isPathActive(link.path);
              const path = link.useId ? (submissionId ? `/repair/${submissionId}` : '/') : link.path;
              return (
                <button 
                  key={i}
                  onClick={() => navigate(path)}
                  title={link.title}
                  className={cn(
                    "w-10 h-10 flex items-center justify-center rounded-xl transition-all duration-150",
                    active ? (link.admin ? "text-error bg-surface-container border border-error/20 shadow-sm" : "text-indigo-400 bg-surface-container border border-indigo-400/20 shadow-sm") : (link.admin ? "text-machined-text-dim hover:text-error hover:bg-surface-container/80" : "text-machined-text-dim hover:text-on-surface hover:bg-surface-container/80")
                  )}
                >
                  <link.icon className="w-5 h-5" />
                </button>
              )
            })}
          </nav>
          <div className="mt-auto flex flex-col gap-4 w-full items-center px-1 pb-2">
            <button 
              onClick={onThemeToggle}
              title={theme === 'dark' ? "Switch to Light Mode" : "Switch to Dark Mode"}
              className="w-10 h-10 flex items-center justify-center text-machined-text-dim hover:text-on-surface transition-all active:scale-95"
            >
              {theme === 'dark' ? <Sun className="w-5 h-5" /> : <Moon className="w-5 h-5" />}
            </button>
            <button 
              onClick={() => navigate('/')}
              title="Start new repair session"
              className={cn(
                "w-full py-3 text-sm font-medium rounded-md transition-all active:scale-95 border text-center flex items-center justify-center",
                isPathActive('/') && location.pathname === '/' 
                  ? "bg-primary text-on-primary border-primary shadow-[0_0_15px_rgba(99,102,241,0.3)]" 
                  : "bg-primary-container text-on-primary-container border-outline-variant hover:brightness-105"
              )}
            >
              <Code className="w-5 h-5" />
            </button>
          </div>
        </aside>

        {/* Main Content */}
        <main className="flex-1 flex overflow-hidden bg-surface-container-lowest">
          {children}
        </main>
      </div>

      {/* Footer (Logs/Diff/Tests) */}
      <footer className="h-auto min-h-[3rem] py-2 md:py-0 md:h-12 bg-machined-footer border-t border-machined-border flex flex-col md:flex-row justify-between items-center px-4 z-50 shrink-0 gap-2 overflow-x-auto no-scrollbar">
        <div className="flex items-center gap-4 w-full md:w-auto shrink-0">
          <button 
            onClick={() => navigate('/history')}
            className={cn(
              "flex items-center gap-2 rounded-md px-3 py-2 transition-all shrink-0",
              isPathActive('/history') ? "bg-surface-container text-on-surface" : "text-machined-text-dim hover:bg-surface-container/70 hover:text-on-surface"
            )}
          >
            <History className="w-4 h-4 text-emerald-400" />
            <span className="font-mono text-[11px] uppercase tracking-widest font-bold text-on-surface-variant hidden sm:inline-block">HISTORY</span>
          </button>
          <div className="h-4 w-px bg-machined-border" />
          <div className="flex items-center gap-2 sm:gap-3 shrink-0">
            <button 
              onClick={() => submissionId && navigate(`/repair/${submissionId}`)}
              className={cn(
                "flex items-center gap-2 rounded-md px-3 py-2 transition-all shrink-0",
                submissionId ? (isPathActive('/repair') ? "bg-surface-container text-on-surface" : "text-machined-text-dim hover:bg-surface-container/70 hover:text-on-surface") : "opacity-30 cursor-not-allowed"
              )}
              disabled={!submissionId}
            >
              <List className="w-4 h-4" />
              <span className="font-mono text-[11px] uppercase tracking-widest font-bold text-on-surface-variant hidden sm:inline-block">LOGS</span>
            </button>
            <button 
              onClick={() => submissionId && navigate(`/iteration/${submissionId}`)}
              className={cn(
                "flex items-center gap-2 rounded-md px-3 py-2 transition-all shrink-0",
                submissionId ? (isPathActive('/iteration') ? "bg-surface-container text-on-surface" : "text-machined-text-dim hover:bg-surface-container/70 hover:text-on-surface") : "opacity-30 cursor-not-allowed"
              )}
              disabled={!submissionId}
            >
              <Diff className="w-4 h-4" />
              <span className="font-mono text-[11px] uppercase tracking-widest font-bold text-on-surface-variant hidden sm:inline-block">DIFF</span>
            </button>
            <button 
              onClick={() => submissionId && navigate(`/tests/${submissionId}`)}
              className={cn(
                "flex items-center gap-2 rounded-md px-3 py-2 transition-all shrink-0",
                submissionId ? (isPathActive('/tests') ? "bg-surface-container text-on-surface" : "text-machined-text-dim hover:bg-surface-container/70 hover:text-on-surface") : "opacity-30 cursor-not-allowed"
              )}
              disabled={!submissionId}
            >
              <CheckCircle2 className="w-4 h-4" />
              <span className="font-mono text-[11px] uppercase tracking-widest font-bold text-on-surface-variant hidden sm:inline-block">TESTS</span>
            </button>
          </div>
        </div>
        <div className="flex items-center gap-3 text-sm shrink-0 self-start md:self-auto w-full md:w-auto justify-between md:justify-end">
          <div className="flex items-center">
            {submissionId && (
              <span className="font-mono text-[11px] text-outline mr-4">Node: <span className="text-primary">{submissionId.substring(0, 8)}</span></span>
            )}
            <span className="font-mono text-[11px] text-machined-text-dim">
              {
                isPathActive('/repair') ? 'Repairing' : 
                location.pathname === '/' ? 'Analyzing' :
                (isPathActive('/history') || isPathActive('/iteration') || isPathActive('/tests')) ? 'Auditing' : 
                'Idle'
              }
            </span>
          </div>
          {isPathActive('/repair') && (
            <button 
              onClick={() => navigate('/')}
              className="ml-2 px-3 py-1 bg-error/15 text-error border border-error/30 rounded-md text-[11px] font-semibold hover:bg-error/25 transition-all"
            >
              Cancel
            </button>
          )}
        </div>
      </footer>

      {/* Mobile NavBar */}
      <nav className="md:hidden flex items-center justify-around bg-machined-sidebar border-t border-machined-border h-14 shrink-0 px-2 overflow-x-auto no-scrollbar gap-2 z-50">
        {navLinks.map((link, i) => {
          const active = isPathActive(link.path);
          const path = link.useId ? (submissionId ? `/repair/${submissionId}` : '/') : link.path;
          return (
            <button 
              key={i}
              onClick={() => navigate(path)}
              title={link.title}
              className={cn(
                "w-10 h-10 shrink-0 flex items-center justify-center rounded-xl transition-all duration-150",
                active ? (link.admin ? "text-error bg-surface-container border border-error/20 shadow-sm" : "text-indigo-400 bg-surface-container border border-indigo-400/20 shadow-sm") : (link.admin ? "text-machined-text-dim hover:text-error hover:bg-surface-container/80" : "text-machined-text-dim hover:text-on-surface hover:bg-surface-container/80")
              )}
            >
              <link.icon className="w-5 h-5" />
            </button>
          )
        })}
        <button 
          onClick={onThemeToggle}
          title="Toggle Theme"
          className="w-10 h-10 shrink-0 flex items-center justify-center text-machined-text-dim hover:text-on-surface transition-all active:scale-95 ml-auto"
        >
          {theme === 'dark' ? <Sun className="w-5 h-5" /> : <Moon className="w-5 h-5" />}
        </button>
      </nav>
    </div>
  );
};
