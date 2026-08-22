import { Link } from "react-router-dom";
import { useEffect, useState } from "react";
import { apiRequest } from "../api";
import { Card, EmptyState } from "../components/ui";
import { useNotifications } from "../components/Notifications";
import type { Job } from "../types";

type HomeState = {
  api_configured: boolean;
  profile_entry_count: number;
  recent_jobs: Job[];
  current_draft: { id: string; job_target_id: string; updated_at: string } | null;
  version_count: number;
  data_directory: string;
};

const emptyHome: HomeState = {
  api_configured: false,
  profile_entry_count: 0,
  recent_jobs: [],
  current_draft: null,
  version_count: 0,
  data_directory: "仅桌面应用可查看",
};

export function HomePage() {
  const { notify } = useNotifications();
  const [state, setState] = useState<HomeState>(emptyHome);
  useEffect(() => {
    if (!window.shadowDesktop) return;
    apiRequest<HomeState>("/api/home").then(setState).catch((error) => notify(error.message, "error"));
  }, [notify]);

  return (
    <main className="page" aria-labelledby="page-title">
      <p className="eyebrow">影子简历助手</p>
      <h1 id="page-title">首页</h1>
      <p className="description">资料、岗位与简历草稿都保存在这台电脑。</p>
      <div className="status-grid">
        <Card title="个人资料"><strong>{state.profile_entry_count}</strong><p>条经历和能力记录</p><Link to="/profile">维护资料</Link></Card>
        <Card title="AI 服务"><strong>{state.api_configured ? "已配置" : "未配置"}</strong><p>生成时需要联网调用模型</p><Link to="/settings">打开设置</Link></Card>
        <Card title="历史版本"><strong>{state.version_count}</strong><p>个主动保存的版本</p></Card>
      </div>
      <div className="section-heading"><h2>最近岗位</h2><Link className="button-link" to="/jobs">新建岗位</Link></div>
      <Card>
        {state.recent_jobs.length === 0 ? <EmptyState title="还没有目标岗位" description="粘贴岗位 JD 后，即可生成针对这份岗位的简历。" /> : (
          <ul className="record-list">{state.recent_jobs.map((job) => <li key={job.id}><div><strong>{job.title || "未命名岗位"}</strong><span>{job.company || "未填写公司"}</span></div><span>{job.status}</span></li>)}</ul>
        )}
      </Card>
      <p className="path-text">本地数据目录：{state.data_directory}</p>
    </main>
  );
}
