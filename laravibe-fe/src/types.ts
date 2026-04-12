export type View = 'analyzer' | 'repair' | 'history' | 'iteration' | 'tests' | 'admin';

export interface LogEntry {
  timestamp: string;
  type: 'ITERATION' | 'INFO' | 'BOOST' | 'TEST' | 'AI';
  message: string;
  id: string;
}

export interface HistoryItem {
  id: string;
  title: string;
  codeSnippet: string[];
  status: 'COMMITTED' | 'ACTIVE' | 'ROLLED_BACK' | 'ARCHIVED';
  date: string;
}

export interface DiffLine {
  type: 'added' | 'removed' | 'neutral';
  content: string;
  lineNumber?: number | string;
}

export interface DiagnosticInsight {
  id: string;
  title: string;
  description: string;
  suggested: string;
  confidence: number;
}
