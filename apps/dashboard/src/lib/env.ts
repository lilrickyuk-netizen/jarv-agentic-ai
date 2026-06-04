/**
 * JARV Dashboard Environment Configuration
 * Type-safe environment variable access
 */

function getEnvVar(key: string, defaultValue?: string): string {
  const value = process.env[key] || defaultValue;

  if (!value) {
    throw new Error(`Missing environment variable: ${key}`);
  }

  return value;
}

function getOptionalEnvVar(key: string, defaultValue?: string): string | undefined {
  return process.env[key] || defaultValue;
}

function getBooleanEnvVar(key: string, defaultValue: boolean = false): boolean {
  const value = process.env[key];
  if (!value) return defaultValue;
  return value.toLowerCase() === 'true' || value === '1';
}

export const env = {
  // API Configuration
  apiUrl: getEnvVar('NEXT_PUBLIC_API_URL', 'http://localhost:8000'),
  wsUrl: getEnvVar('NEXT_PUBLIC_WS_URL', 'ws://localhost:8000/ws'),

  // Environment
  nodeEnv: getEnvVar('NODE_ENV', 'development'),
  isDevelopment: process.env.NODE_ENV === 'development',
  isProduction: process.env.NODE_ENV === 'production',

  // Feature Flags
  experimentalFeatures: getBooleanEnvVar('NEXT_PUBLIC_EXPERIMENTAL_FEATURES', false),
  voiceEnabled: getBooleanEnvVar('NEXT_PUBLIC_VOICE_ENABLED', false),

  // Analytics (Optional)
  googleAnalyticsId: getOptionalEnvVar('NEXT_PUBLIC_GOOGLE_ANALYTICS_ID'),
  sentryDsn: getOptionalEnvVar('NEXT_PUBLIC_SENTRY_DSN'),
} as const;

// Type for environment
export type Env = typeof env;

// Export for convenience
export default env;
