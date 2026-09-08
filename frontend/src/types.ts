export interface Drawing {
  id: number;
  filename: string;
  status: string;
}

export interface Issue {
  id: number;
  issue_id: string;
  rule_id: string;
  category: string;
  severity: string;
  status: string;
  title: string;
  description: string;
  recommendation: string;
  confidence: number;
  pos_x: number | null;
  pos_y: number | null;
  related_entities: string[];
}

export interface Entity {
  id: number;
  entity_id: string;
  type: string;
  tag: string;
  pos_x: number;
  pos_y: number;
}
