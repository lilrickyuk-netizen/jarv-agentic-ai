import { clearTokens, getAccessToken } from '@/lib/auth';
import { env } from '@/lib/env';

export interface ApiResponse<T> {
  data?: T;
  error?: string;
  details?: unknown;
  status?: number;
}

export interface HealthResponse {
  status: string;
  timestamp: string;
  service: string;
  version: string;
}

export interface ReadyChecks {
  status: string;
  timestamp?: string;
  checks?: Record<string, { status: string; [key: string]: unknown }>;
}

export interface VersionResponse {
  service: string;
  version: string;
  environment: string;
  python_version: string;
  platform: string;
  timestamp: string;
  features: Record<string, boolean>;
  configuration: Record<string, string | number | boolean>;
}

class ApiClient {
  private readonly baseUrl = typeof window === 'undefined'
    ? env.apiUrl.replace(/\/+$/, '')
    : '/api/backend';
  private refreshPromise: Promise<boolean> | null = null;

  private expireSession(): void {
    clearTokens();
    if (typeof window !== 'undefined' && window.location.pathname !== '/login') {
      window.location.replace('/login');
    }
  }

  private async refreshAccessToken(): Promise<boolean> {
    if (typeof window === 'undefined') return false;
    if (!this.refreshPromise) {
      this.refreshPromise = (async () => {
        const refreshToken = window.localStorage.getItem('refresh_token');
        if (!refreshToken) return false;
        try {
          const response = await fetch(`${this.baseUrl}/auth/refresh`, {
            method: 'POST',
            headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
            body: JSON.stringify({ refresh_token: refreshToken }),
          });
          if (!response.ok) {
            clearTokens();
            return false;
          }
          const tokens = await response.json() as { access_token?: string; refresh_token?: string };
          if (!tokens.access_token || !tokens.refresh_token) {
            clearTokens();
            return false;
          }
          window.localStorage.setItem('access_token', tokens.access_token);
          window.localStorage.setItem('refresh_token', tokens.refresh_token);
          return true;
        } catch {
          return false;
        } finally {
          this.refreshPromise = null;
        }
      })();
    }
    return this.refreshPromise;
  }

  async get<T>(path: string): Promise<ApiResponse<T>> {
    return this.request<T>(path, { method: 'GET' });
  }

  async post<T = unknown>(path: string, body?: unknown): Promise<ApiResponse<T>> {
    return this.request<T>(path, {
      method: 'POST',
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  }

  async upload<T>(path: string, body: FormData): Promise<ApiResponse<T>> {
    const send = () => {
      const headers = new Headers({ Accept: 'application/json' });
      const token = getAccessToken();
      if (token) headers.set('Authorization', `Bearer ${token}`);
      return fetch(`${this.baseUrl}${path.startsWith('/') ? path : `/${path}`}`, {
        method: 'POST',
        headers,
        body,
      });
    };

    try {
      let response = await send();
      if (response.status === 401 && await this.refreshAccessToken()) response = await send();
      if (response.status === 401) this.expireSession();
      const payload: unknown = await response.json().catch(() => null);
      if (!response.ok) {
        const detail = typeof payload === 'object' && payload !== null
          ? (payload as { detail?: unknown; message?: unknown }).detail
            ?? (payload as { message?: unknown }).message
          : payload;
        return {
          error: typeof detail === 'string' ? detail : `Request failed (${response.status})`,
          details: payload,
          status: response.status,
        };
      }
      return { data: payload as T, status: response.status };
    } catch (error) {
      return {
        error: error instanceof Error ? error.message : 'Network request failed',
        details: error,
      };
    }
  }

  checkHealth(): Promise<ApiResponse<HealthResponse>> {
    return this.get<HealthResponse>('/health');
  }

  checkReady(): Promise<ApiResponse<ReadyChecks>> {
    return this.get<ReadyChecks>('/ready');
  }

  getVersion(): Promise<ApiResponse<VersionResponse>> {
    return this.get<VersionResponse>('/version');
  }

  private async request<T>(path: string, init: RequestInit): Promise<ApiResponse<T>> {
    const headers = new Headers(init.headers);
    headers.set('Accept', 'application/json');
    if (init.body !== undefined) headers.set('Content-Type', 'application/json');

    const token = getAccessToken();
    if (token) headers.set('Authorization', `Bearer ${token}`);

    const url = `${this.baseUrl}${path.startsWith('/') ? path : `/${path}`}`;
    const send = () => {
      const requestHeaders = new Headers(headers);
      const token = getAccessToken();
      if (token) requestHeaders.set('Authorization', `Bearer ${token}`);
      else requestHeaders.delete('Authorization');
      return fetch(url, { ...init, headers: requestHeaders });
    };

    try {
      let response = await send();
      const isAuthRequest = path.startsWith('/auth/login') || path.startsWith('/auth/refresh');
      if (response.status === 401 && !isAuthRequest) {
        if (await this.refreshAccessToken()) response = await send();
        if (response.status === 401) this.expireSession();
      }
      const contentType = response.headers.get('content-type') || '';
      const payload: unknown = contentType.includes('application/json')
        ? await response.json()
        : await response.text();

      if (!response.ok) {
        const detail = typeof payload === 'object' && payload !== null
          ? (payload as { detail?: unknown; message?: unknown }).detail
            ?? (payload as { message?: unknown }).message
          : payload;
        return {
          error: typeof detail === 'string' ? detail : `Request failed (${response.status})`,
          details: payload,
          status: response.status,
        };
      }

      return { data: payload as T, status: response.status };
    } catch (error) {
      return {
        error: error instanceof Error ? error.message : 'Network request failed',
        details: error,
      };
    }
  }
}

export const apiClient = new ApiClient();
export default apiClient;
