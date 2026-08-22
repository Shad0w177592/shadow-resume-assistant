export {};

declare global {
  interface Window {
    shadowDesktop?: {
      health(): Promise<{ status: string }>;
      request<T>(path: string, method?: string, body?: unknown): Promise<T>;
      pickDocument(): Promise<string | null>;
      pickPhoto?(): Promise<string | null>;
      pickBackup(): Promise<string | null>;
      transcribeAudio(bytes: ArrayBuffer, mediaType?: string): Promise<{ text: string }>;
      platform: string;
    };
  }
}
