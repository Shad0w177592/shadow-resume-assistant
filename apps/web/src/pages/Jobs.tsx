import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiRequest } from "../api";
import { Button, Card, EmptyState, TextInput } from "../components/ui";
import { useNotifications } from "../components/Notifications";
import type { Job, ResumeDraft } from "../types";

export function JobsPage() {
  const { notify } = useNotifications();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [company, setCompany] = useState("");
  const [title, setTitle] = useState("");
  const [jd, setJd] = useState("");
  const [notes, setNotes] = useState("");
  const [draft, setDraft] = useState<ResumeDraft | null>(null);
  const [generating, setGenerating] = useState(false);

  useEffect(() => {
    if (!window.shadowDesktop) return;
    apiRequest<Job[]>("/api/jobs").then(setJobs).catch((error) => notify(error.message, "error"));
  }, [notify]);

  async function create(event: FormEvent) {
    event.preventDefault();
    if (!jd.trim()) { notify("请粘贴岗位 JD", "error"); return; }
    try {
      const job = await apiRequest<Job>("/api/jobs", "POST", { company: company || null, title: title || null, jd_text: jd, notes: notes || null });
      setJobs((current) => [job, ...current]); setCompany(""); setTitle(""); setJd(""); setNotes("");
      notify("岗位已创建", "success");
    } catch (error) { notify(error instanceof Error ? error.message : "创建失败", "error"); }
  }

  async function generate(job: Job) {
    setGenerating(true);
    try { setDraft(await apiRequest<ResumeDraft>(`/api/jobs/${job.id}/generate`, "POST")); }
    catch (error) { notify(error instanceof Error ? error.message : "生成失败", "error"); }
    finally { setGenerating(false); }
  }

  async function duplicate(job: Job) {
    const copied = await apiRequest<Job>(`/api/jobs/${job.id}/duplicate`, "POST");
    setJobs((current) => [copied, ...current]);
  }

  async function remove(job: Job) {
    if (!window.confirm(`确认删除岗位“${job.title || "未命名岗位"}”？个人资料和其他岗位不会被删除。`)) return;
    await apiRequest(`/api/jobs/${job.id}`, "DELETE");
    setJobs((current) => current.filter((item) => item.id !== job.id));
  }

  return (
    <main className="page wide-page" aria-labelledby="page-title">
      <p className="eyebrow">影子简历助手</p><h1 id="page-title">目标岗位</h1>
      <p className="description">每个岗位的 JD、配置和简历草稿相互独立。</p>
      <div className="jobs-layout">
        <div>
          <Card title="新建岗位"><form onSubmit={create} className="entry-form"><div className="form-grid"><TextInput label="公司（选填）" value={company} onChange={(event) => setCompany(event.target.value)} /><TextInput label="岗位名称（选填）" value={title} onChange={(event) => setTitle(event.target.value)} /></div><label className="field"><span>岗位 JD</span><textarea required value={jd} onChange={(event) => setJd(event.target.value)} /></label><label className="field"><span>备注（选填）</span><textarea value={notes} onChange={(event) => setNotes(event.target.value)} /></label><Button type="submit">保存岗位</Button></form></Card>
          <Card title="岗位列表">{jobs.length === 0 ? <EmptyState title="还没有岗位" description="复制粘贴一份招聘信息，创建第一个目标岗位。" /> : <ul className="record-list">{jobs.map((job) => <li key={job.id}><div><strong>{job.title || "未命名岗位"}</strong><span>{job.company || "未填写公司"}</span></div><div className="inline-actions"><Button disabled={generating} onClick={() => generate(job)}>{generating ? "生成中…" : "生成草稿"}</Button><Link className="button-link compact" to={`/workbench/${job.id}`}>工作台</Link><Button className="ghost" onClick={() => duplicate(job)}>复制</Button><Button className="danger" onClick={() => remove(job)}>删除</Button></div></li>)}</ul>}</Card>
        </div>
        <div><Card title="只读预览">{!draft ? <EmptyState title="尚未生成" description="生成时会直接结合岗位要求选择和组织个人资料。" /> : <article className="resume-preview"><header><h2>{draft.document.personal_info.name || "姓名"}</h2><p>{draft.document.personal_info.contacts.join(" · ")}</p></header>{draft.document.sections.map((section) => <section key={section.section_id}><h3>{section.title}</h3>{section.blocks.map((block) => <div key={block.block_id}><strong>{block.heading}</strong><small>{block.meta}</small>{block.paragraphs.map((paragraph) => <p key={paragraph.paragraph_id}>{paragraph.text}</p>)}</div>)}</section>)}</article>}</Card></div>
      </div>
    </main>
  );
}
