import { NextRequest, NextResponse } from 'next/server';
import { timeoutFor } from '@/lib/backend-timeout';

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
  // The public address the operator used, so links the backend builds (such as calendar feed links) point at it.
  headers.set('x-forwarded-host', request.headers.get('x-forwarded-host') || request.headers.get('host') || request.nextUrl.host);
  headers.set('x-forwarded-proto', request.headers.get('x-forwarded-proto') || request.nextUrl.protocol.replace(':', ''));

  try {
    const body = ['GET', 'HEAD'].includes(request.method) ? undefined : await request.arrayBuffer();
    const timeoutMs = timeoutFor(path);
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
  } catch (error) {
    // A backend that is slow to answer is not an unreachable one: say which it was.
    if (error instanceof Error && (error.name === 'TimeoutError' || error.name === 'AbortError')) {
      return NextResponse.json({ detail: `JAI's backend is running but took longer than ${Math.round(timeoutFor(path) / 1000)} `
        + 'seconds to answer this request.' }, { status: 504 });
    }
    return NextResponse.json({ detail: 'Backend API is unreachable' }, { status: 502 });
  }
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
export const PATCH = forward;
export const DELETE = forward;