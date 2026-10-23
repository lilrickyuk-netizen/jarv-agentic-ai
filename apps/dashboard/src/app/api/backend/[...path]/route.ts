import { NextRequest, NextResponse } from 'next/server';

type RouteContext = { params: { path: string[] } };

async function forward(request: NextRequest, { params }: RouteContext) {
  const path = params.path.map(encodeURIComponent).join('/');
  const backendUrl = (process.env.JARV_BACKEND_URL || 'http://127.0.0.1:8000').replace(/\/+$/, '');
  const target = new URL(`${path}${request.nextUrl.search}`, `${backendUrl}/`);
  const headers = new Headers();

  for (const name of ['accept', 'authorization', 'content-type', 'origin', 'x-request-id']) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }

  try {
    const body = ['GET', 'HEAD'].includes(request.method) ? undefined : await request.arrayBuffer();
    const timeoutMs = path.endsWith('/status') && path.includes('/voicebox/') ? 10 * 60 * 1000 : 30000;
    const response = await fetch(target, {
      method: request.method,
      headers,
      body,
      cache: 'no-store',
      signal: AbortSignal.timeout(timeoutMs),
    });
    const responseHeaders = new Headers();
    for (const name of ['content-type', 'content-disposition', 'cache-control']) {
      const value = response.headers.get(name);
      if (value) responseHeaders.set(name, value);
    }
    return new Response(response.body, { status: response.status, headers: responseHeaders });
  } catch {
    return NextResponse.json({ detail: 'Backend API is unreachable' }, { status: 502 });
  }
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
export const PATCH = forward;
export const DELETE = forward;