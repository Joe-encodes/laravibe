// Force Vite HMR reload
import React, { useState, useEffect } from 'react';
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
  BarChart2,
  Server,
  Database
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

  const [health, setHealth] = useState<{status?: string, docker?: string, ai?: string, db?: string} | null>(null);

  useEffect(() => {
    const checkHealth = async () => {
      try {
        const res = await fetch('/api/health');
        if (res.ok) {
          const data = await res.json();
          setHealth(data);
        }
      } catch (err) {
        console.error('Failed to fetch health status:', err);
      }
    };
    checkHealth();
    
    // Poll every 10 seconds
    const interval = setInterval(checkHealth, 10000);
    return () => clearInterval(interval);
  }, []);

  const StatusItem = ({ icon: Icon, label, status, color }: { icon: any, label: string, status: string, color: string }) => (
    <div className="flex items-center gap-2 group cursor-help" title={`${label}: ${status}`}>
      <Icon className={cn("w-3.5 h-3.5", color)} />
      <div className="flex flex-col">
        <span className="text-[8px] font-bold text-outline/60 uppercase leading-none mb-0.5">{label}</span>
        <span className={cn("text-[9px] font-black uppercase leading-none tracking-tighter", color)}>{status}</span>
      </div>
    </div>
  );

  const navLinks = [
    { path: '/', icon: Code, title: 'Analyzer workspace' },
    { path: '/repair', icon: Bug, title: 'Active repair stream', useId: true },
    { path: '/history', icon: History, title: 'Operational archives' },
    { path: '/reports', icon: BarChart2, title: 'Analytics reports' },
    { path: '/admin', icon: ShieldAlert, title: 'Admin dashboard', admin: true },
  ];

  return (
    <div className="h-screen flex flex-col overflow-hidden bg-surface-container-lowest text-on-surface transition-colors duration-300 font-sans">
      {/* TopAppBar */}
      <header className="bg-machined-header flex justify-between items-center w-full px-4 h-14 border-b border-machined-border z-50 shrink-0">
        <div className="flex items-center gap-3">
          {/* Brand Logo */}
          <div className="flex items-center gap-1.5 group select-none cursor-pointer" onClick={() => navigate('/')}>
            <span className="text-secondary text-sm font-black opacity-60 group-hover:opacity-100 transition-opacity">&gt;_</span>
            <span className="relative">
              <span className="absolute inset-0 blur-md bg-primary/20 rounded pointer-events-none" />
              <span
                className="relative font-black text-base tracking-[0.15em] uppercase"
                style={{
                  background: 'linear-gradient(90deg, #c0c1ff 0%, #8b5cf6 40%, #4edea3 80%, #c0c1ff 100%)',
                  backgroundSize: '200% auto',
                  WebkitBackgroundClip: 'text',
                  WebkitTextFillColor: 'transparent',
                  backgroundClip: 'text',
                  animation: 'gradient-shift 4s linear infinite',
                }}
              >
                LARAVIBE
              </span>
            </span>
            <span className="text-primary font-black text-base animate-pulse leading-none">█</span>
          </div>
          <span className="text-[10px] font-bold text-machined-text-dim border border-machined-border px-1.5 py-0.5 rounded-sm">V1.0</span>
        </div>
        
        <div className="flex items-center gap-2">
          {/* Unified Machined HUD Block */}
          <div className="flex items-center bg-surface-container-high/40 dark:bg-machined-sidebar/40 border border-machined-border rounded-lg p-1 backdrop-blur-md shadow-lg">
            <div className="flex items-center gap-4 px-3 py-1 border-r border-machined-border/50">
              <StatusItem 
                icon={Server} 
                label="SANDBOX" 
                status={health?.docker === 'connected' ? 'ACTIVE' : 'OFFLINE'} 
                color={health?.docker === 'connected' ? 'text-secondary' : 'text-error'} 
              />
              <div className="w-[1px] h-5 bg-machined-border/30"></div>
              <StatusItem 
                icon={Activity} 
                label="ORCHESTRATOR" 
                status={health?.status === 'ok' ? 'READY' : 'WAITING'} 
                color={health?.status === 'ok' ? 'text-primary' : 'text-outline'} 
              />
              <div className="w-[1px] h-5 bg-machined-border/30"></div>
              <StatusItem 
                icon={Database} 
                label="SYSTEM_DB" 
                status={health?.db === 'connected' ? 'LINKED' : 'OFFLINE'} 
                color={health?.db === 'connected' ? 'text-secondary' : 'text-error'} 
              />
            </div>
            
            <div className="flex items-center gap-2 pl-3 pr-2">
              <button
                onClick={onThemeToggle}
                className="p-1.5 hover:bg-surface-container-highest/50 rounded-md transition-all text-machined-text-dim hover:text-on-surface"
                title="Toggle Theme"
              >
                {theme === 'dark' ? <Sun className="w-3.5 h-3.5" /> : <Moon className="w-3.5 h-3.5" />}
              </button>
              
              <div className="w-[1px] h-5 bg-machined-border/30"></div>
              
              <div className="flex items-center gap-2.5 px-1.5">
                <div className="flex flex-col items-end">
                  <span className="text-[7px] font-black text-outline/60 uppercase tracking-widest leading-none mb-0.5">AUTH_LVL</span>
                  <span className="text-[9px] font-mono text-on-surface font-black tracking-tighter leading-none">MASTER_ADM</span>
                </div>
                <button 
                  onClick={onSignOut}
                  className="p-1.5 hover:bg-error/10 hover:text-error rounded-md transition-all text-machined-text-dim"
                  title="Sign Out"
                >
                  <LogOut className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          </div>
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
                <div key={i} className="relative group">
                  {active && (
                    <div className="absolute -left-4 top-1/2 -translate-y-1/2 w-1 h-6 bg-primary rounded-r-full shadow-[0_0_10px_rgba(192,193,255,0.8)] animate-pulse" />
                  )}
                  <button 
                    onClick={() => navigate(path)}
                    title={link.title}
                    className={cn(
                      "w-10 h-10 flex items-center justify-center rounded-xl transition-all duration-300 relative z-10",
                      active ? (link.admin ? "text-error bg-error/10 border border-error/30 shadow-[0_0_15px_rgba(239,68,68,0.15)]" : "text-primary bg-primary/10 border border-primary/30 primary-glow") : (link.admin ? "text-machined-text-dim hover:text-error hover:bg-surface-container/80" : "text-machined-text-dim hover:text-on-surface hover:bg-surface-container/80 hover:shadow-lg")
                    )}
                  >
                    <link.icon className={cn("w-5 h-5 transition-transform duration-300", active && "scale-110")} />
                  </button>
                </div>
              )
            })}
          </nav>
        </aside>

        {/* Main Content */}
        <main className="flex-1 flex overflow-hidden bg-surface-container-lowest">
          {children}
        </main>
      </div>

      {/* Footer */}
      <footer className="h-12 bg-machined-footer border-t border-machined-border flex justify-between items-center px-4 z-50 shrink-0">
        <div className="flex items-center gap-3">
          <button 
            onClick={() => submissionId && navigate(`/repair/${submissionId}`)}
            className={cn(
              "flex items-center gap-2 rounded-md px-3 py-1.5 transition-all border border-transparent hover:border-outline-variant/30",
              submissionId ? (isPathActive('/repair') ? "bg-surface-container text-on-surface shadow-sm" : "text-machined-text-dim hover:bg-surface-container/70") : "opacity-30 cursor-not-allowed"
            )}
            disabled={!submissionId}
          >
            <List className="w-4 h-4" />
            <span className="text-[10px] font-black tracking-widest uppercase">Logs</span>
          </button>
          <button 
            onClick={() => submissionId && navigate(`/iteration/${submissionId}`)}
            className={cn(
              "flex items-center gap-2 rounded-md px-3 py-1.5 transition-all border border-transparent hover:border-outline-variant/30",
              submissionId ? (isPathActive('/iteration') ? "bg-surface-container text-on-surface shadow-sm" : "text-machined-text-dim hover:bg-surface-container/70") : "opacity-30 cursor-not-allowed"
            )}
            disabled={!submissionId}
          >
            <Diff className="w-4 h-4" />
            <span className="text-[10px] font-black tracking-widest uppercase">Diff</span>
          </button>
          <button 
            onClick={() => submissionId && navigate(`/tests/${submissionId}`)}
            className={cn(
              "flex items-center gap-2 rounded-md px-3 py-1.5 transition-all border border-transparent hover:border-outline-variant/30",
              submissionId ? (isPathActive('/tests') ? "bg-surface-container text-on-surface shadow-sm" : "text-machined-text-dim hover:bg-surface-container/70") : "opacity-30 cursor-not-allowed"
            )}
            disabled={!submissionId}
          >
            <CheckCircle2 className="w-4 h-4" />
            <span className="text-[10px] font-black tracking-widest uppercase">Tests</span>
          </button>
        </div>

        <div className="flex items-center gap-3">
          {submissionId && (
            <span className="text-[10px] font-black text-outline/50 uppercase tracking-widest">
              Node: <span className="text-primary">{submissionId.substring(0, 8)}</span>
            </span>
          )}
          <span className="text-[10px] font-black text-machined-text-dim/40 tracking-[0.2em] uppercase">
            {isPathActive('/repair') ? 'Repair_Stream' : location.pathname === '/' ? 'Idle' : 'Audit'}
          </span>
        </div>
      </footer>

      {/* Mobile NavBar */}
      <nav className="md:hidden flex items-center justify-around bg-machined-sidebar border-t border-machined-border h-14 shrink-0 px-2 z-50">
        {navLinks.map((link, i) => {
          const active = isPathActive(link.path);
          const path = link.useId ? (submissionId ? `/repair/${submissionId}` : '/') : link.path;
          return (
            <button 
              key={i}
              onClick={() => navigate(path)}
              className={cn(
                "w-10 h-10 flex items-center justify-center rounded-xl transition-all",
                active ? "text-primary bg-surface-container border border-primary/20" : "text-machined-text-dim"
              )}
            >
              <link.icon className="w-5 h-5" />
            </button>
          )
        })}
      </nav>
    </div>
  );
};
