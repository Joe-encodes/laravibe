export type View = 'analyzer' | 'repair' | 'history' | 'iteration' | 'tests' | 'admin';

export interface LogEntry {
  timestamp: string;
  type: 'ITERATION' | 'INFO' | 'BOOST' | 'TEST' | 'AI';
  message: string;
  id: string;
}

export interface Iteration {
  id: string;
  submission_id: string;
  iteration_num: number;
  status: string;
  ai_response?: string;
  patch_diff?: string;
  pest_result?: string;
  boost_context?: string;
  created_at: string;
}

export interface Submission {
  id: string;
  status: 'pending' | 'running' | 'success' | 'failed';
  original_code: string;
  final_code?: string;
  total_iterations: number;
  mutation_score?: number;
  created_at: string;
  iterations: Iteration[];
}

export interface EvaluateCaseResult {
  sample_file: string;
  status: string;
  iterations: number;
  mutation_score?: number;
  submission_id?: string;
}

export interface EvaluationExperiment {
  id: string;
  status: string;
  cases: EvaluateCaseResult[];
  created_at: string;
}

export interface BoostContext {
  component_type: string;
  context_text: string;
  schema?: any;
}

export interface Patch {
  path: string;
  action: 'full_replace' | 'create_file';
  content: string;
}

export interface DiagnosticInsight {
  title: string;
  description: string;
}
