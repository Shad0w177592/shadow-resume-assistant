import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiRequest } from "../api";
import { Card, EmptyState } from "../components/ui";
import { useNotifications } from "../components/Notifications";
import type { Job } from "../types";

export function WorkbenchLandingPage() {
  const { notify } = useNotifications();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!window.shadowDesktop) {
      setLoaded(true);
      return;
    }
    apiRequest<Job[]>("/api/jobs")
      .then(setJobs)
      .catch((error) => notify(error.message, "error"))
      .finally(() => setLoaded(true));
  }, [notify]);

  return (
    <main className="page" aria-labelledby="page-title">
      <p className="eyebrow">影子简历助手</p>
      <h1 id="page-title">简历工作台</h1>
      <p className="description">选择一个目标岗位，进入对应的简历生成和修改工作台。</p>
      <Card title="选择目标岗位">
        {!loaded ? (
          <p>正在加载目标岗位…</p>
        ) : jobs.length === 0 ? (
          <EmptyState title="还没有目标岗位" description="请先录入岗位 JD，再回来生成简历。" action={<Link className="button-link" to="/jobs">前往目标岗位</Link>} />
        ) : (
          <ul className="record-list">
            {jobs.map((job) => (
              <li key={job.id}>
                <div>
                  <strong>{job.title || "未命名岗位"}</strong>
                  <span>{job.company || "未填写公司"}</span>
                </div>
                <Link className="button-link compact" to={`/workbench/${job.id}`}>打开工作台</Link>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </main>
  );
}
