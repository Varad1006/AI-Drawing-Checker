export type Pt = [number, number];
export type BBox = [number, number, number, number];
export type Severity = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW';
export type IssueStatus = 'OPEN' | 'ACCEPTED' | 'REJECTED' | 'FIXED';
type Style = { ls?: 'dashed'; layer?: string };

export type Prim =
  | ({ t: 'line'; a: Pt; b: Pt } & Style)
  | ({ t: 'poly'; pts: Pt[]; closed?: boolean; fill?: boolean } & Style)
  | ({ t: 'circle'; c: Pt; r: number; fill?: boolean } & Style)
  | ({ t: 'arc'; c: Pt; r: number; a0: number; a1: number } & Style)
  | ({
      t: 'text';
      p: Pt;
      s: string;
      h: number;
      rot?: number;
      ha?: 'left' | 'center' | 'right';
      va?: 'baseline' | 'middle' | 'top';
    } & Style);

export type TextPrim = Extract<Prim, { t: 'text' }>;

export interface Label {
  dx: number;
  dy: number;
  h: number;
  rot?: number;
  style?: 'single' | 'split';
}

export interface Entity {
  id: string;
  type: string;
  tag: string | null;
  block: string | null;
  x: number;
  y: number;
  rot: number;
  sx: number;
  sy: number;
  layer?: string;
  label: Label | null;
  attrs: Record<string, string>;
  box?: BBox;
}

export interface Line {
  id: string;
  kind: 'process' | 'signal';
  pts: Pt[];
  tag: string | null;
  layer?: string;
  tag_pos?: { p: Pt; h: number; rot?: number; ha?: string; va?: string } | null;
}

export interface TitleField {
  value: string;
  p: Pt;
  h: number;
}

export interface TitleBlock {
  block: string | null;
  x: number;
  y: number;
  sx: number;
  sy: number;
  rot: number;
  fields: Record<string, TitleField>;
}

export interface DrawingDoc {
  version: number;
  source: { format: 'dxf' | 'pdf'; units: string };
  bounds: BBox;
  blocks: Record<string, Prim[]>;
  entities: Entity[];
  lines: Line[];
  background: Prim[];
  title_block: TitleBlock | null;
  meta: { connectivity?: boolean; [k: string]: unknown };
}

export type Op = { op: string; [k: string]: unknown };

export interface Issue {
  key: string;
  rule_id: string;
  source: 'rule' | 'ai';
  category: string;
  severity: Severity;
  title: string;
  description: string;
  recommendation: string;
  confidence: number;
  entities: string[];
  lines: string[];
  bbox: BBox | null;
  location: Pt | null;
  fix: { label: string; ops: Op[] } | null;
  status: IssueStatus;
  comment: string;
  ai_rev?: number;
}

export interface Stats {
  open: number;
  accepted: number;
  rejected: number;
  fixed: number;
  fixable: number;
  by_severity: Record<Severity, number>;
}

export interface DrawingSummary {
  id: number;
  filename: string;
  format: 'dxf' | 'pdf';
  created_at: string;
  updated_at: string;
  head_rev: number;
  max_rev: number;
  ai_status: 'idle' | 'running' | 'done' | 'error';
  ai_error: string | null;
  stats: Stats;
}

export interface RevisionInfo {
  rev_no: number;
  author: 'import' | 'user' | 'auto-fix' | 'ai' | 'assistant';
  summary: string;
  created_at: string;
  changed: string[];
}

export interface AIInfo {
  enabled: boolean;
  provider: string;
  model: string | null;
}

export interface ChatMessage {
  id: number;
  role: 'user' | 'assistant';
  content: string;
  actions: string[];
  rev_no: number | null;
  engine: string;
  created_at: string;
}

export interface Detail {
  drawing: DrawingSummary;
  document: DrawingDoc;
  topology: { tol: number; attachments: Record<string, [string, 'start' | 'end'][]> };
  issues: Issue[];
  revisions: RevisionInfo[];
  changed: string[];
  ai: AIInfo;
  messages?: string[];
  chat?: ChatMessage[];
}

export interface RuleInfo {
  id: string;
  title: string;
  category: string;
  severity: Severity;
  description: string;
  needs_topology: boolean;
}

export interface ComponentType {
  type: string;
  name: string;
  category: string;
  prefixes: string[];
}
