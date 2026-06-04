'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { apiClient } from '@/lib/api';

interface AgentInfo {
  name: string;
  role: string;
  authority_level: number;
  tool_count: number;
  tools: string[];
  implemented: boolean;
}
interface Department {
  department: string;
  agent_count: number;
  agents: AgentInfo[];
}

export default function DepartmentsPage() {
  const router = useRouter();
  const [depts, setDepts] = useState<Department[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      setLoading(true);
      const res = await apiClient.get<Department[]>('/api/agents/departments/overview');
      if (res.error) setError(res.error);
      else if (res.data) setDepts(res.data);
      setLoading(false);
    })();
  }, []);

  const totalAgents = depts.reduce((n, d) => n + d.agent_count, 0);

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-7xl mx-auto">
        <div className="mb-8">
          <h1 className="text-4xl font-bold mb-2">Departments</h1>
          <p className="text-muted-foreground">
            The autonomous software company — {totalAgents} lead agents across {depts.length} departments.
            Click an agent to run a role task.
          </p>
        </div>

        {loading && (
          <div className="flex items-center justify-center py-12">
            <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-primary"></div>
          </div>
        )}
        {error && (
          <div className="bg-destructive/10 border border-destructive text-destructive px-4 py-3 rounded-lg mb-6">
            <p className="font-semibold">Error loading departments</p>
            <p className="text-sm">{error}</p>
          </div>
        )}

        {!loading && !error && depts.length === 0 && (
          <div className="bg-card border rounded-lg p-12 text-center text-muted-foreground">
            No departments configured yet.
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {depts.map((d) => (
            <section key={d.department} className="bg-card border rounded-lg p-6">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-xl font-semibold">{d.department}</h2>
                <span className="text-xs bg-primary/10 text-primary px-2 py-1 rounded">
                  {d.agent_count} agents
                </span>
              </div>
              <div className="space-y-2">
                {d.agents.map((a) => (
                  <button
                    key={a.name}
                    onClick={() => router.push(`/dashboard/agents`)}
                    className="w-full text-left border rounded-md p-3 hover:border-primary transition-colors"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-medium">{a.name}</span>
                      <span className="text-xs text-muted-foreground">
                        L{a.authority_level} · {a.tool_count} tools
                        {a.implemented ? '' : ' · not implemented'}
                      </span>
                    </div>
                    <p className="text-xs text-muted-foreground mt-1">{a.role}</p>
                    {a.tools.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-2">
                        {a.tools.slice(0, 8).map((t) => (
                          <span key={t} className="text-[10px] bg-muted px-1.5 py-0.5 rounded font-mono">
                            {t}
                          </span>
                        ))}
                      </div>
                    )}
                  </button>
                ))}
              </div>
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}
