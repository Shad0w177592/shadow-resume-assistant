import { createContext, useCallback, useContext, useMemo, useState, type PropsWithChildren } from "react";

type Notice = { id: number; message: string; kind: "info" | "success" | "error" };
type NotificationContextValue = { notify: (message: string, kind?: Notice["kind"]) => void };

const NotificationContext = createContext<NotificationContextValue | null>(null);

export function NotificationProvider({ children }: PropsWithChildren) {
  const [notices, setNotices] = useState<Notice[]>([]);
  const notify = useCallback((message: string, kind: Notice["kind"] = "info") => {
    const id = Date.now() + Math.random();
    setNotices((current) => [...current, { id, message, kind }]);
    window.setTimeout(() => setNotices((current) => current.filter((item) => item.id !== id)), 3500);
  }, []);
  const value = useMemo(() => ({ notify }), [notify]);
  return (
    <NotificationContext.Provider value={value}>
      {children}
      <div className="notifications" aria-live="polite">
        {notices.map((notice) => <div key={notice.id} className={`notice ${notice.kind}`}>{notice.message}</div>)}
      </div>
    </NotificationContext.Provider>
  );
}

export function useNotifications() {
  const value = useContext(NotificationContext);
  if (!value) throw new Error("useNotifications must be used inside NotificationProvider");
  return value;
}

