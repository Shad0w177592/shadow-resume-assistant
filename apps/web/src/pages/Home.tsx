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
    <main className="page home-page" aria-labelledby="page-title">
      <section className="home-hero">
        <div className="home-hero-copy">
          <p className="eyebrow">LOCAL AI RESUME DESK · 本地简历工作台</p>
          <h1 id="page-title">首页</h1>
          <h2>把真实经历，整理成更贴近目标岗位的简历。</h2>
          <p className="description">从个人资料、岗位要求到修改和导出，按照一条清楚的路径完成。资料与草稿保存在这台电脑，只有生成内容时调用你配置的 AI 服务。</p>
          <div className="home-hero-actions"><Link className="button-link" to="/workbench">开始生成简历</Link><Link className="text-link" to="/profile">先整理个人资料 →</Link></div>
        </div>
        <div className="home-hero-note"><span aria-hidden="true">01</span><strong>真实资料优先</strong><p>先保留事实，再根据岗位调整表达和顺序。</p></div>
      </section>

      <section className="home-section" aria-labelledby="workspace-title">
        <div className="section-heading"><div><span>WORKSPACE</span><h2 id="workspace-title">你的工作区</h2></div></div>
        <div className="status-grid">
          <Card title="个人资料"><strong>{state.profile_entry_count}</strong><p>条经历和能力记录</p><Link to="/profile">维护资料 →</Link></Card>
          <Card title="AI 服务"><strong>{state.api_configured ? "已配置" : "未配置"}</strong><p>生成时需要联网调用模型</p><Link to="/settings">打开设置 →</Link></Card>
          <Card title="历史版本"><strong>{state.version_count}</strong><p>个主动保存的版本</p></Card>
        </div>
      </section>

      <section className="home-section home-flow" aria-labelledby="flow-title">
        <div className="section-heading"><div><span>HOW IT WORKS</span><h2 id="flow-title">三步完成一份岗位简历</h2></div></div>
        <ol><li><span>01</span><strong>整理资料</strong><p>导入或填写真实经历、技能和成果。</p></li><li><span>02</span><strong>粘贴岗位</strong><p>保存岗位 JD，告诉 AI 这份简历投向哪里。</p></li><li><span>03</span><strong>生成与修改</strong><p>选择要改的栏目，在工作台确认、保存并导出。</p></li></ol>
      </section>

      <section className="home-section" aria-labelledby="recent-jobs-title">
        <div className="section-heading"><div><span>RECENT TARGETS</span><h2 id="recent-jobs-title">最近岗位</h2></div><Link className="button-link secondary-link" to="/jobs">＋ 新建岗位</Link></div>
        <Card>
          {state.recent_jobs.length === 0 ? <EmptyState title="还没有目标岗位" description="粘贴岗位 JD 后，即可生成针对这份岗位的简历。" /> : (
            <ul className="record-list">{state.recent_jobs.map((job) => <li key={job.id}><div><strong>{job.title || "未命名岗位"}</strong><span>{job.company || "未填写公司"}</span></div><span>{job.status}</span></li>)}</ul>
          )}
        </Card>
      </section>
      <p className="path-text home-data-path">本地数据目录：{state.data_directory}</p>
    </main>
  );}
