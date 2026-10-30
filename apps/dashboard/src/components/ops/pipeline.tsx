'use client';

export interface Partner {
  id: string;
  name: string;
  type: string;
  status: string;
  contact: string | null;
  email: string | null;
  description: string | null;
  estimated_value: number | null;
  score: number | null;
  reasons: string[] | null;
  verified: boolean;
  history: { status?: string; note?: string; notes?: string | null; at: string }[];
}

export interface Deal {
  id: string;
  title: string;
  stage: string;
  value: number | null;
  notes: string | null;
  contact_id: string | null;
  expected_close_date: string | null;
}

export interface Pipeline {
  deals_by_stage: Record<string, { count: number; value: number }>;
  open_pipeline_value: number;
  won_value: number;
  win_rate: number | null;
  partners_by_status: Record<string, number>;
  partners: Partner[];
  deals: Deal[];
}

export const DEAL_STAGES = ['prospecting', 'qualified', 'proposal', 'negotiation', 'closed_won', 'closed_lost'];
export const PARTNER_STAGES = ['shortlisted', 'contacted', 'in_discussion', 'proposal', 'negotiating', 'active', 'paused', 'declined'];
