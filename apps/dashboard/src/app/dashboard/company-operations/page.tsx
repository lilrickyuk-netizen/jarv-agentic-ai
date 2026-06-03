'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { apiClient } from '@/lib/api';

interface CompanyRole {
  id: string;
  workspace_id: string;
  role_name: string;
  role_type: string;
  department: string;
  description: string | null;
  responsibilities: string[];
  kpis: Record<string, any>;
  authority_level: number;
  is_active: boolean;
  is_automated: boolean;
  parent_role_id: string | null;
  total_agents: number;
  active_agents: number;
  tasks_completed: number;
  tasks_failed: number;
  created_at: string;
  updated_at: string;
}

interface CompanyStats {
  total_roles: number;
  active_roles: number;
  automated_roles: number;
  total_departments: number;
  total_agents_assigned: number;
  total_tasks_completed: number;
  tasks_failed: number;
  by_department: Record<string, Record<string, number>>;
  by_role_type: Record<string, number>;
}

interface DepartmentInfo {
  department: string;
  total_roles: number;
  active_roles: number;
  total_agents: number;
  tasks_completed: number;
}

export default function CompanyOperationsPage() {
  const router = useRouter();
  const [roles, setRoles] = useState<CompanyRole[]>([]);
  const [stats, setStats] = useState<CompanyStats | null>(null);
  const [departments, setDepartments] = useState<DepartmentInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedDepartment, setSelectedDepartment] = useState<string>('all');
  const [selectedRoleType, setSelectedRoleType] = useState<string>('all');
  const [showActiveOnly, setShowActiveOnly] = useState(false);

  useEffect(() => {
    fetchData();
  }, [selectedDepartment, selectedRoleType, showActiveOnly]);

  const fetchData = async () => {
    setLoading(true);
    setError(null);

    try {
      // Fetch roles
      const params = new URLSearchParams();
      if (selectedDepartment !== 'all') {
        params.append('department', selectedDepartment);
      }
      if (selectedRoleType !== 'all') {
        params.append('role_type', selectedRoleType);
      }
      if (showActiveOnly) {
        params.append('is_active', 'true');
      }

      const rolesResponse = await apiClient.get<CompanyRole[]>(
        `/company/roles/list?${params.toString()}`
      );

      if (rolesResponse.error) {
        setError(rolesResponse.error);
      } else if (rolesResponse.data) {
        setRoles(rolesResponse.data);
      }

      // Fetch stats
      const statsResponse = await apiClient.get<CompanyStats>('/company/stats');
      if (!statsResponse.error && statsResponse.data) {
        setStats(statsResponse.data);
      }

      // Fetch departments
      const deptsResponse = await apiClient.get<DepartmentInfo[]>('/company/departments');
      if (!deptsResponse.error && deptsResponse.data) {
        setDepartments(deptsResponse.data);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch company data');
    } finally {
      setLoading(false);
    }
  };

  const getRoleTypeColor = (roleType: string) => {
    const colors: Record<string, string> = {
      leadership: 'bg-purple-100 text-purple-800',
      management: 'bg-blue-100 text-blue-800',
      operations: 'bg-green-100 text-green-800',
      specialist: 'bg-orange-100 text-orange-800',
      support: 'bg-gray-100 text-gray-800',
    };
    return colors[roleType] || 'bg-gray-100 text-gray-800';
  };

  const getAuthorityColor = (level: number) => {
    if (level >= 8) return 'text-red-600 font-bold';
    if (level >= 5) return 'text-orange-600 font-semibold';
    if (level >= 3) return 'text-yellow-600';
    return 'text-green-600';
  };

  const calculateSuccessRate = (completed: number, failed: number) => {
    const total = completed + failed;
    if (total === 0) return 0;
    return Math.round((completed / total) * 100);
  };

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-4xl font-bold mb-2">Company Operations</h1>
          <p className="text-muted-foreground">
            Organizational structure, roles, and operational performance
          </p>
        </div>

        {/* Loading State */}
        {loading && (
          <div className="flex items-center justify-center py-12">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary"></div>
          </div>
        )}

        {/* Error State */}
        {error && (
          <div className="bg-destructive/10 border border-destructive text-destructive px-4 py-3 rounded-lg mb-6">
            <p className="font-semibold">Error Loading Company Data</p>
            <p className="text-sm">{error}</p>
          </div>
        )}

        {/* Statistics Cards */}
        {!loading && stats && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Total Roles
              </h3>
              <p className="text-3xl font-bold">{stats.total_roles}</p>
              <p className="text-xs text-muted-foreground mt-1">
                {stats.active_roles} active
              </p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Departments
              </h3>
              <p className="text-3xl font-bold text-blue-600">{stats.total_departments}</p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Total Agents
              </h3>
              <p className="text-3xl font-bold text-purple-600">{stats.total_agents_assigned}</p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Tasks Completed
              </h3>
              <p className="text-3xl font-bold text-green-600">{stats.total_tasks_completed}</p>
              {stats.tasks_failed > 0 && (
                <p className="text-xs text-red-600 mt-1">{stats.tasks_failed} failed</p>
              )}
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Automated Roles
              </h3>
              <p className="text-3xl font-bold">{stats.automated_roles}</p>
              <p className="text-xs text-muted-foreground mt-1">
                {Math.round((stats.automated_roles / stats.total_roles) * 100)}% automation
              </p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Success Rate
              </h3>
              <p className="text-3xl font-bold">
                {calculateSuccessRate(stats.total_tasks_completed, stats.tasks_failed)}%
              </p>
            </div>
          </div>
        )}

        {/* Department Breakdown */}
        {!loading && departments.length > 0 && (
          <div className="bg-card border rounded-lg p-6 mb-8">
            <h2 className="text-2xl font-bold mb-4">Department Breakdown</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {departments.map((dept) => (
                <div
                  key={dept.department}
                  className="bg-muted rounded-lg p-4 hover:border-primary transition-colors border border-transparent"
                >
                  <h3 className="font-semibold text-lg mb-2">{dept.department}</h3>
                  <div className="space-y-1 text-sm">
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Roles:</span>
                      <span className="font-medium">{dept.total_roles} ({dept.active_roles} active)</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Agents:</span>
                      <span className="font-medium">{dept.total_agents}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Tasks:</span>
                      <span className="font-medium text-green-600">{dept.tasks_completed}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Role Type Distribution */}
        {!loading && stats && Object.keys(stats.by_role_type).length > 0 && (
          <div className="bg-card border rounded-lg p-6 mb-8">
            <h2 className="text-2xl font-bold mb-4">Role Type Distribution</h2>
            <div className="flex flex-wrap gap-3">
              {Object.entries(stats.by_role_type).map(([type, count]) => (
                <div
                  key={type}
                  className={`px-4 py-2 rounded-lg ${getRoleTypeColor(type)}`}
                >
                  <span className="font-medium">{type.replace(/_/g, ' ')}</span>
                  <span className="ml-2 font-bold">{count}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Filters */}
        {!loading && (
          <div className="flex flex-col md:flex-row gap-4 mb-6">
            {/* Department Filter */}
            <div className="flex-1">
              <label className="block text-sm font-medium mb-2">Department</label>
              <select
                value={selectedDepartment}
                onChange={(e) => setSelectedDepartment(e.target.value)}
                className="w-full px-3 py-2 border rounded-md bg-card"
              >
                <option value="all">All Departments</option>
                {departments.map((dept) => (
                  <option key={dept.department} value={dept.department}>
                    {dept.department}
                  </option>
                ))}
              </select>
            </div>

            {/* Role Type Filter */}
            {stats && (
              <div className="flex-1">
                <label className="block text-sm font-medium mb-2">Role Type</label>
                <select
                  value={selectedRoleType}
                  onChange={(e) => setSelectedRoleType(e.target.value)}
                  className="w-full px-3 py-2 border rounded-md bg-card"
                >
                  <option value="all">All Types</option>
                  {Object.keys(stats.by_role_type).map((type) => (
                    <option key={type} value={type}>
                      {type.replace(/_/g, ' ')}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {/* Active Filter */}
            <div className="flex items-end">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={showActiveOnly}
                  onChange={(e) => setShowActiveOnly(e.target.checked)}
                  className="w-4 h-4"
                />
                <span className="text-sm">Active only</span>
              </label>
            </div>
          </div>
        )}

        {/* Empty State */}
        {!loading && !error && roles.length === 0 && (
          <div className="bg-card border rounded-lg p-12 text-center">
            <h3 className="text-xl font-semibold mb-2">No Company Roles</h3>
            <p className="text-muted-foreground">
              {selectedDepartment !== 'all' || selectedRoleType !== 'all' || showActiveOnly
                ? 'No roles match the selected filters'
                : 'No company roles have been defined yet'}
            </p>
          </div>
        )}

        {/* Roles List */}
        {!loading && roles.length > 0 && (
          <div className="space-y-4">
            {roles.map((role) => (
              <div
                key={role.id}
                className={`bg-card border rounded-lg p-6 hover:border-primary transition-colors ${
                  !role.is_active ? 'opacity-60' : ''
                }`}
              >
                {/* Header */}
                <div className="flex items-start justify-between mb-4">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-2">
                      <h3 className="text-xl font-semibold">{role.role_name}</h3>
                      <span className={`px-2 py-1 text-xs rounded ${getRoleTypeColor(role.role_type)}`}>
                        {role.role_type}
                      </span>
                      {role.is_automated && (
                        <span className="px-2 py-1 text-xs rounded bg-indigo-100 text-indigo-800">
                          Automated
                        </span>
                      )}
                      {!role.is_active && (
                        <span className="px-2 py-1 text-xs rounded bg-gray-100 text-gray-800">
                          Inactive
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-muted-foreground mb-1">
                      <span className="font-medium">{role.department}</span> Department
                    </p>
                    {role.description && (
                      <p className="text-sm text-muted-foreground">{role.description}</p>
                    )}
                  </div>
                  <div className="ml-4 text-right">
                    <p className="text-sm text-muted-foreground">Authority Level</p>
                    <p className={`text-2xl font-bold ${getAuthorityColor(role.authority_level)}`}>
                      {role.authority_level}
                    </p>
                  </div>
                </div>

                {/* Responsibilities */}
                {role.responsibilities && role.responsibilities.length > 0 && (
                  <div className="mb-4">
                    <p className="text-sm font-medium mb-2">Responsibilities:</p>
                    <ul className="grid grid-cols-1 md:grid-cols-2 gap-2">
                      {role.responsibilities.map((resp, idx) => (
                        <li key={idx} className="text-sm text-muted-foreground flex items-start gap-2">
                          <span className="text-primary mt-1">•</span>
                          <span>{resp}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Stats Grid */}
                <div className="grid grid-cols-2 md:grid-cols-5 gap-4 pt-4 border-t">
                  <div>
                    <p className="text-xs text-muted-foreground">Total Agents</p>
                    <p className="text-lg font-semibold">{role.total_agents}</p>
                  </div>

                  <div>
                    <p className="text-xs text-muted-foreground">Active Agents</p>
                    <p className="text-lg font-semibold text-blue-600">{role.active_agents}</p>
                  </div>

                  <div>
                    <p className="text-xs text-muted-foreground">Tasks Completed</p>
                    <p className="text-lg font-semibold text-green-600">{role.tasks_completed}</p>
                  </div>

                  <div>
                    <p className="text-xs text-muted-foreground">Tasks Failed</p>
                    <p className="text-lg font-semibold text-red-600">{role.tasks_failed}</p>
                  </div>

                  <div>
                    <p className="text-xs text-muted-foreground">Success Rate</p>
                    <p className="text-lg font-semibold">
                      {calculateSuccessRate(role.tasks_completed, role.tasks_failed)}%
                    </p>
                  </div>
                </div>

                {/* KPIs */}
                {role.kpis && Object.keys(role.kpis).length > 0 && (
                  <div className="mt-4 pt-4 border-t">
                    <p className="text-sm font-medium mb-2">Key Performance Indicators:</p>
                    <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                      {Object.entries(role.kpis).map(([key, value]) => (
                        <div key={key} className="bg-muted rounded p-2">
                          <p className="text-xs text-muted-foreground">
                            {key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}
                          </p>
                          <p className="text-sm font-medium">{String(value)}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Results Count */}
        {!loading && roles.length > 0 && (
          <div className="mt-6 text-center text-sm text-muted-foreground">
            Showing {roles.length} role{roles.length !== 1 ? 's' : ''}
          </div>
        )}
      </div>
    </div>
  );
}
