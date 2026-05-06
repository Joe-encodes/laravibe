import React from 'react';
import { Shield, Lock, ArrowRight, Terminal, Cpu, Eye, EyeOff, AlertCircle } from 'lucide-react';
import { motion } from 'motion/react';
import { cn } from '../lib/utils';

interface LoginViewProps {
  onLogin: (sessionToken: string) => void;
}

export const LoginView: React.FC<LoginViewProps> = ({ onLogin }) => {
  const [masterKey, setMasterKey] = React.useState('');
  const [showKey, setShowKey] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [isLoading, setIsLoading] = React.useState(false);

  /**
   * Security Model:
   * 1. User enters master key → sent ONCE to POST /api/auth/login
   * 2. Backend verifies key → returns a short-lived JWT session token (8h)
   * 3. FE stores the JWT, NOT the master key
   * 4. All subsequent API calls use the JWT session token
   * The master key is never stored in localStorage or the JS bundle.
   */
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!masterKey.trim()) return;

    setIsLoading(true);
    setError(null);

    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: masterKey }),
      });

      if (response.ok) {
        const data = await response.json();
        // Store the JWT session token — never the raw master key
        const sessionToken: string = data.access_token;
        localStorage.setItem('laravibe_session_token', sessionToken);
        onLogin(sessionToken);
      } else if (response.status === 429) {
        setError('Too many attempts. Please try again later.');
      } else {
        setError('Access denied. Invalid credentials.');
      }
    } catch (err) {
      console.error('Login error:', err);
      setError('Connection failed. Service unavailable.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-surface-container-lowest overflow-hidden">
      {/* Background Orbs */}
      <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-primary/10 rounded-full blur-[120px] animate-pulse pointer-events-none" />
      <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-secondary/10 rounded-full blur-[120px] animate-pulse delay-1000 pointer-events-none" />

      <motion.div
        initial={{ opacity: 0, y: 20, scale: 0.95 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.3, ease: 'easeOut' }}
        className="w-full max-w-md p-8 relative"
      >
        <div className="bg-surface-container-low/40 backdrop-blur-3xl border border-outline-variant/30 p-8 rounded-2xl shadow-2xl relative overflow-hidden">
          {/* Top gradient accent */}
          <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-primary/60 to-transparent" />

          <div className="flex flex-col items-center text-center mb-8">
            <div className="w-16 h-16 bg-surface-container-high border border-outline-variant rounded-2xl flex items-center justify-center mb-5 relative">
              <Shield className="w-8 h-8 text-primary" />
              <div className="absolute inset-0 bg-primary/20 blur-xl rounded-full animate-pulse opacity-50" />
            </div>
            <h1 className="font-mono text-2xl font-black tracking-tight text-on-surface mb-1">Laravibe access</h1>
            <p className="text-on-surface-variant font-mono text-sm opacity-80">Secure access required to continue</p>
          </div>

          {error && (
            <motion.div
              initial={{ opacity: 0, y: -8 }}
              animate={{ opacity: 1, y: 0 }}
              className="mb-6 flex items-start gap-2 bg-error/10 border border-error/30 rounded-lg px-4 py-3"
            >
              <AlertCircle className="w-4 h-4 text-error shrink-0 mt-0.5" />
              <span className="mono text-[10px] font-bold text-error leading-relaxed">{error}</span>
            </motion.div>
          )}

          <form onSubmit={handleSubmit} className="space-y-5">
            <div className="space-y-2">
              <label className="mono text-[10px] font-bold text-outline uppercase tracking-widest ml-1">Admin Access Key</label>
              <div className="relative group">
                <div className="absolute inset-y-0 left-4 flex items-center pointer-events-none">
                  <Lock className="w-4 h-4 text-outline group-focus-within:text-primary transition-colors" />
                </div>
                <input
                  type={showKey ? 'text' : 'password'}
                  value={masterKey}
                  onChange={(e) => setMasterKey(e.target.value)}
                  placeholder="Enter access key"
                  className="w-full bg-surface-container-highest/50 border border-outline-variant/50 rounded-xl py-4 pl-12 pr-12 mono text-sm text-on-surface placeholder:text-outline/60 focus:outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/20 transition-all"
                  autoFocus
                  autoComplete="current-password"
                />
                <button
                  type="button"
                  onClick={() => setShowKey(!showKey)}
                  className="absolute inset-y-0 right-4 flex items-center text-outline hover:text-on-surface transition-colors"
                  tabIndex={-1}
                >
                  {showKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            <button
              type="submit"
              disabled={isLoading || !masterKey.trim()}
              className={cn(
                "w-full py-4 rounded-xl mono text-sm font-black uppercase tracking-[0.2em] flex items-center justify-center gap-3 transition-all",
                isLoading || !masterKey.trim()
                  ? "bg-surface-container-highest text-outline cursor-not-allowed"
                  : "bg-primary text-on-primary hover:brightness-110 active:scale-[0.98] shadow-xl shadow-primary/20"
              )}
            >
              {isLoading ? (
                <><Cpu className="w-4 h-4 animate-spin" /> Verifying...</>
              ) : (
                <><ArrowRight className="w-4 h-4" /> Sign In</>
              )}
            </button>
          </form>

        </div>

        {/* Corner accents */}
        <div className="absolute -top-4 -left-4 w-12 h-12 border-t-2 border-l-2 border-primary/20 rounded-tl-3xl pointer-events-none" />
        <div className="absolute -bottom-4 -right-4 w-12 h-12 border-b-2 border-r-2 border-secondary/20 rounded-br-3xl pointer-events-none" />
      </motion.div>
    </div>
  );
};
