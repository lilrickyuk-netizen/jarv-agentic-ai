/**
 * Frontend API Health Check Route
 * Proxies health check to backend API
 */

import { NextResponse } from 'next/server';
import { apiClient } from '@/lib/api';

export async function GET() {
  try {
    const response = await apiClient.checkHealth();

    if (response.error) {
      return NextResponse.json(
        {
          error: 'Backend API is not accessible',
          message: response.error,
          details: response.details,
        },
        { status: 503 }
      );
    }

    return NextResponse.json({
      frontend: {
        status: 'healthy',
        service: 'jarv-dashboard',
        version: '1.0.0',
      },
      backend: response.data,
    });
  } catch (error) {
    return NextResponse.json(
      {
        error: 'Health check failed',
        message: error instanceof Error ? error.message : 'Unknown error',
      },
      { status: 500 }
    );
  }
}
