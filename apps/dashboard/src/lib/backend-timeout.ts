/** How long the dashboard waits for JAI's backend: long for Voicebox generation, 90 seconds for Talk with JAI's
 * tools (JAI's reasoning core thinks before it answers, and a mission start may take a moment), 30 seconds for
 * everything else. */
export function timeoutFor(path: string): number {
  if (path.endsWith('/status') && path.includes('/voicebox/')) return 10 * 60 * 1000;
  if (path.includes('voice/live/tool')) return 90 * 1000;
  return 30000;
}
