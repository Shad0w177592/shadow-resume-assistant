export {};

declare global {
  interface Window {
    shadowDesktop?: {
      health(): Promise<{ status: string }>;
      request<T>(path: string, method?: string, body?: unknown): Promise<T>;
      pickDocument(): Promise<string | null>;
      pickPhoto?(): Promise<string | null>;
      pickBackup(): Promise<string | null>;
      changeDataDirectory?(): Promise<{ dataDirectory: string; backupPath: string | null; oldDirectory?: string; oldDirectoryPreserved: boolean } | null>;
      transcribeAudio(bytes: ArrayBuffer, mediaType?: "audio/wav" | "audio/wave"): Promise<{ text: string }>;
      platform: string;
    };
  }
}
