import { useState } from "react";
import { apiRequest } from "../api";
import { Button, Card, EmptyState } from "../components/ui";
import { useNotifications } from "../components/Notifications";

type Candidate = {
  id: string;
  section_key: string;
  title: string | null;
  payload: { content?: string };
  source_locator: { page: number; block_id: string };
  confidence: "clear" | "uncertain";
  duplicate_of: string | null;
};

type ImportResult = {
  id: string;
  original_name: string;
  status: string;
  parsed: { failure_reason?: string; pages: Array<{ page_number: number; blocks: Array<{ block_id: string; text: string }> }> };
  candidates: Candidate[];
};

const labels: Record<string, string> = {
  summary: "自我介绍",
  education: "教育经历", work: "工作经历", internship: "实习经历", project: "项目经历",
  campus: "校园、社团及志愿经历", skills: "专业技能", awards: "证书与奖项", other: "其他",
};

export function ImportPage() {
  const { notify } = useNotifications();
  const [result, setResult] = useState<ImportResult | null>(null);
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [sections, setSections] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);

  async function choose() {
    if (!window.shadowDesktop) { notify("请在桌面应用中选择文件", "error"); return; }
    const path = await window.shadowDesktop.pickDocument();
    if (!path) return;
    setLoading(true);
    try {
      const imported = await apiRequest<ImportResult>("/api/imports/from-path", "POST", { path });
      setResult(imported);
      setSelected(Object.fromEntries(imported.candidates.map((item) => [item.id, true])));
      setSections(Object.fromEntries(imported.candidates.map((item) => [item.id, item.section_key])));
    } catch (error) { notify(error instanceof Error ? error.message : "导入失败", "error"); }
    finally { setLoading(false); }
  }

  async function confirm() {
    if (!result) return;
    const decisions = result.candidates.map((item) => ({
      candidate_id: item.id,
      action: selected[item.id] ? "accept" : "ignore",
      section_key: sections[item.id],
    }));
    const summary = await apiRequest<{ accepted: number; ignored: number }>(`/api/imports/${result.id}/confirm`, "POST", { decisions });
    const wordHint = result.original_name.toLowerCase().endsWith(".docx") ? "；后续导出 Word 时将保留原文件排版" : "";
    notify(`已写入 ${summary.accepted} 条，忽略 ${summary.ignored} 条${wordHint}`, "success");
  }

  const original = result?.parsed.pages.flatMap((page) => page.blocks.map((block) => ({ ...block, page: page.page_number }))) || [];
  return (
    <main className="page wide-page" aria-labelledby="page-title">
      <p className="eyebrow">影子简历助手</p><h1 id="page-title">导入与确认</h1>
      <p className="description">支持 PDF、Word、TXT 和 Markdown。候选内容由你确认后才写入个人资料。</p>
      <Button onClick={choose} disabled={loading}>{loading ? "正在解析…" : "选择文件"}</Button>
      {!result ? <Card><EmptyState title="尚未选择文件" description="原文件只复制到本机应用数据目录。" /></Card> : result.status !== "parsed" ? <Card title="无法导入"><p role="alert">{result.parsed.failure_reason || `文件状态：${result.status}`}</p></Card> : (
        <div className="import-layout">
          <Card title={`原文 · ${result.original_name}`}><div className="source-blocks">{original.map((block) => <article key={`${block.page}-${block.block_id}`}><small>第 {block.page} 页</small><p>{block.text}</p></article>)}</div></Card>
          <Card title="候选资料">{result.candidates.map((candidate) => <article className="candidate" key={candidate.id}><label className="check"><input type="checkbox" checked={selected[candidate.id] ?? false} onChange={(event) => setSelected((current) => ({ ...current, [candidate.id]: event.target.checked }))} /><strong>{candidate.title || "导入内容"}</strong></label><div className="candidate-badges"><span>{candidate.confidence === "clear" ? "归类明确" : "归类不确定"}</span>{candidate.duplicate_of && <span className="warning">疑似重复</span>}</div><label className="field"><span>写入栏目</span><select value={sections[candidate.id]} onChange={(event) => setSections((current) => ({ ...current, [candidate.id]: event.target.value }))}>{Object.entries(labels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label><p>{candidate.payload.content}</p><small>来源：第 {candidate.source_locator.page} 页 / {candidate.source_locator.block_id}</small></article>)}<Button onClick={confirm}>确认写入资料库</Button></Card>
        </div>
      )}
    </main>
  );
}
