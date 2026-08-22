export type HealthResponse = { status: string; service: string; version: string };

export class LocalApiClient {
  constructor(private readonly invoke: <T>(path: string, init?: RequestInit) => Promise<T>) {}

  health(): Promise<HealthResponse> {
    return this.invoke<HealthResponse>("/health");
  }

  sessionCheck(): Promise<{ authenticated: boolean }> {
    return this.invoke<{ authenticated: boolean }>("/api/session-check");
  }
}

