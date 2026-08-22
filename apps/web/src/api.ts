export async function apiRequest<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  if (!window.shadowDesktop) throw new Error("本地桌面服务尚未连接");
  return window.shadowDesktop.request<T>(path, method, body);
}

