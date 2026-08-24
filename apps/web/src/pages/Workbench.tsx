import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { apiRequest } from "../api";
import { convertRecordedAudioToWav } from "../audio";
import { Button, Card, Dialog, EmptyState } from "../components/ui";
import { useNotifications } from "../components/Notifications";
import type { Profile, ResumeDraft } from "../types";

type SectionConfig = { section_key: string; title: string; enabled: boolean; order: number; column: "left" | "right" | "full"; max_entries?: number | null };
type ResumeConfig = { template: "single_column" | "technical_double_column"; page_target: 1 | 2; strategies: string[]; sections: SectionConfig[]; entry_modes: Record<string, "must_include" | "exclude_this_resume" | "ai_decide">; rewrite_sections: string[] };
type EditProposal = { id: string; target_block_id: string; before_text: string; after_text: string; status: string; payload: { instruction: string; reason: string; evidence_ids: string[]; save_scope: string; contains_new_fact: boolean } };
type ResumeVersion = { id: string; name: string; notes: string | null; created_at: string; snapshot: { document: ResumeDraft["document"]; config: ResumeConfig } };
type GeneratedResumeDraft = ResumeDraft & { fact_warnings?: string[] };
function ResumeParagraphEditor({ label, text, expanded, selected, onFocus, onChange }: { label: string; text: string; expanded: boolean; selected: boolean; onFocus: () => void; onChange: (value: string) => void }) {
  const editorRef = useRef<HTMLTextAreaElement | null>(null);

  useLayoutEffect(() => {
    const editor = editorRef.current;
    if (!editor) return;
    if (!expanded) {
      editor.style.height = "";
      return;
    }
    editor.style.height = "0px";
    editor.style.height = `${editor.scrollHeight}px`;
  }, [expanded, text]);

  return <textarea ref={editorRef} aria-label={label} className={`${expanded ? "expanded" : "compact"}${selected ? " selected" : ""}`} value={text} onFocus={onFocus} onChange={(event) => onChange(event.target.value)} />;
}

export function WorkbenchPage() {
  const { jobId = "" } = useParams();
  const { notify } = useNotifications();
  const [config, setConfig] = useState<ResumeConfig | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [draft, setDraft] = useState<ResumeDraft | null>(null);
  const [selectedParagraph, setSelectedParagraph] = useState<string | null>(null);
  const [paragraphsExpanded, setParagraphsExpanded] = useState(true);
  const [busy, setBusy] = useState(false);
  const [instruction, setInstruction] = useState("");
  const [saveScope, setSaveScope] = useState("current_resume");
  const [showGenerateOptions, setShowGenerateOptions] = useState(false);
  const [showPolish, setShowPolish] = useState(false);
  const [polishMethods, setPolishMethods] = useState<string[]>([]);
  const [showFabricationRisk, setShowFabricationRisk] = useState(false);
  const [factWarnings, setFactWarnings] = useState<string[]>([]);
  const [proposal, setProposal] = useState<EditProposal | null>(null);
  const [recording, setRecording] = useState(false);
  const [versions, setVersions] = useState<ResumeVersion[]>([]);
  const [showVersions, setShowVersions] = useState(false);
  const [restoreTarget, setRestoreTarget] = useState<ResumeVersion | null>(null);
  const [comparison, setComparison] = useState<Array<{ block_id: string; change: string }> | null>(null);
  const [blockingOperation, setBlockingOperation] = useState(false);
  const undoStack = useRef<ResumeDraft[]>([]);
  const redoStack = useRef<ResumeDraft[]>([]);
  const dragKey = useRef<string | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);

  useEffect(() => {
    if (!window.shadowDesktop) return;
    Promise.all([
      apiRequest<{ config: ResumeConfig }>(`/api/jobs/${jobId}/resume-config`),
      apiRequest<Profile>("/api/profile"),
    ]).then(([configuration, loadedProfile]) => { setConfig(configuration.config); setProfile(loadedProfile); }).catch((error) => notify(error.message, "error"));
    apiRequest<ResumeDraft>(`/api/jobs/${jobId}/draft`).then(setDraft).catch(() => undefined);
    apiRequest<ResumeVersion[]>(`/api/jobs/${jobId}/versions`).then(setVersions).catch(() => undefined);
  }, [jobId, notify]);

  useEffect(() => () => {
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
    streamRef.current?.getTracks().forEach((track) => track.stop());
  }, []);

  useEffect(() => {
    const handler = (event: BeforeUnloadEvent) => {
      if (!busy && !recording && !blockingOperation && proposal?.status !== "pending") return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [busy, recording, blockingOperation, proposal?.status]);

  useEffect(() => {
    if (!draft || !window.shadowDesktop) return;
    const timer = window.setTimeout(() => {
      apiRequest(`/api/jobs/${jobId}/draft`, "PUT", { document: draft.document }).catch(
        (error) => notify(`草稿自动保存失败：${error.message}`, "error"),
      );
    }, 900);
    return () => window.clearTimeout(timer);
  }, [draft, jobId, notify]);

  function patchConfig(patch: Partial<ResumeConfig>) { setConfig((current) => current ? { ...current, ...patch } : current); }
  function updateSection(key: string, patch: Partial<SectionConfig>) { setConfig((current) => current ? { ...current, sections: current.sections.map((section) => section.section_key === key ? { ...section, ...patch } : section) } : current); }
  function dropSection(target: string) {
    if (!config || !dragKey.current || dragKey.current === target) return;
    const ordered = [...config.sections].sort((a, b) => a.order - b.order);
    const sourceIndex = ordered.findIndex((item) => item.section_key === dragKey.current);
    const targetIndex = ordered.findIndex((item) => item.section_key === target);
    const [source] = ordered.splice(sourceIndex, 1); ordered.splice(targetIndex, 0, source);
    patchConfig({ sections: ordered.map((item, order) => ({ ...item, order })) });
  }
  async function saveConfig() { if (!config) return; await apiRequest(`/api/jobs/${jobId}/resume-config`, "PUT", { config }); notify("简历配置已保存", "success"); }
  function toggleRewriteSection(sectionKey: string) {
    patchConfig({
      rewrite_sections: config?.rewrite_sections.includes(sectionKey)
        ? config.rewrite_sections.filter((item) => item !== sectionKey)
        : [...(config?.rewrite_sections || []), sectionKey],
    });
  }
  async function runGenerate() {
    if (!config) return;
    setBusy(true);
    try {
      await saveConfig();
      const value = await apiRequest<GeneratedResumeDraft>(`/api/jobs/${jobId}/generate`, "POST");
      setDraft(value);
      setFactWarnings(value.fact_warnings || []);
      setShowGenerateOptions(false);
      undoStack.current = []; redoStack.current = [];
    } catch (error) { notify(error instanceof Error ? error.message : "生成失败", "error"); }
    finally { setBusy(false); }
  }

  function editParagraph(paragraphId: string, text: string) {
    if (!draft) return;
    undoStack.current.push(structuredClone(draft)); redoStack.current = [];
    setDraft({ ...draft, document: { ...draft.document, sections: draft.document.sections.map((section) => ({ ...section, blocks: section.blocks.map((block) => ({ ...block, paragraphs: block.paragraphs.map((paragraph) => paragraph.paragraph_id === paragraphId ? { ...paragraph, text } : paragraph) })) })) } });
  }
  function undo() { if (!draft || undoStack.current.length === 0) return; redoStack.current.push(structuredClone(draft)); setDraft(undoStack.current.pop() || draft); }
  function redo() { if (!draft || redoStack.current.length === 0) return; undoStack.current.push(structuredClone(draft)); setDraft(redoStack.current.pop() || draft); }
  async function saveDraft() { if (!draft) return; const saved = await apiRequest<ResumeDraft>(`/api/jobs/${jobId}/draft`, "PUT", { document: draft.document }); setDraft(saved); notify("草稿已保存", "success"); }
  async function saveVersion() {
    if (!draft) { notify("请先生成简历", "error"); return null; }
    await saveDraft();
    const version = await apiRequest<ResumeVersion>(`/api/jobs/${jobId}/versions`, "POST", { name: `版本 ${versions.length + 1}`, notes: null });
    setVersions((current) => [version, ...current]); notify("历史版本已保存", "success"); return version;
  }
  async function exportBoth(saveFirst = false) {
    if (saveFirst && !(await saveVersion())) return;
    setBlockingOperation(true);
    try {
      const result = await apiRequest<{ files: string[]; word_mode: "source_format" | "generated_template" }>(`/api/jobs/${jobId}/export`, "POST", { filename: draft?.document.personal_info.name ? `${draft.document.personal_info.name}-简历` : "影子简历", formats: ["docx", "pdf"] });
      const mode = result.word_mode === "source_format" ? "Word 已保留原文件排版；" : "";
      notify(`${mode}已导出：${result.files.join("；")}`, "success");
    } catch (error) { notify(error instanceof Error ? error.message : "导出失败", "error"); }
    finally { setBlockingOperation(false); }
  }
  async function compareVersion(version: ResumeVersion) { if (!draft) return; const result = await apiRequest<{ changes: Array<{ block_id: string; change: string }> }>(`/api/versions/${version.id}/compare`, "POST", { current_document: draft.document }); setComparison(result.changes); }
  async function restoreVersion(version: ResumeVersion, saveCurrent: boolean) { if (saveCurrent) await saveVersion(); const restored = await apiRequest<ResumeDraft>(`/api/versions/${version.id}/restore`, "POST"); setDraft(restored); setConfig(version.snapshot.config); setRestoreTarget(null); notify("历史版本已恢复为当前草稿", "success"); }
  async function deleteVersion(version: ResumeVersion) { await apiRequest(`/api/versions/${version.id}`, "DELETE"); setVersions((current) => current.filter((item) => item.id !== version.id)); }
  async function editVersionMeta(version: ResumeVersion) {
    const name = window.prompt("版本名称", version.name);
    if (name === null) return;
    const notes = window.prompt("版本备注（可留空）", version.notes || "");
    if (notes === null) return;
    const updated = await apiRequest<ResumeVersion>(`/api/versions/${version.id}`, "PATCH", { name, notes: notes || null });
    setVersions((current) => current.map((item) => item.id === updated.id ? updated : item));
    notify("版本名称和备注已更新", "success");
  }
  async function exportVersion(version: ResumeVersion) {
    const result = await apiRequest<{ files: string[]; word_mode: "source_format" | "generated_template" }>(`/api/versions/${version.id}/export`, "POST", { filename: version.name, formats: ["docx", "pdf"] });
    const mode = result.word_mode === "source_format" ? "Word 已保留原文件排版；" : "";
    notify(`${mode}历史版本已导出：${result.files.join("；")}`, "success");
  }
  async function proposeEdit() {
    if (!selectedParagraph) { notify("请先在画布中选择一个段落", "error"); return; }
    if (!instruction.trim()) { notify("请输入或录制修改要求", "error"); return; }
    try { setProposal(await apiRequest<EditProposal>(`/api/jobs/${jobId}/edit-proposals`, "POST", { target_paragraph_id: selectedParagraph, instruction, save_scope: saveScope })); }
    catch (error) { notify(error instanceof Error ? error.message : "修改建议生成失败", "error"); }
  }
  async function decide(action: "accept" | "reject") {
    if (!proposal) return;
    const updated = await apiRequest<EditProposal>(`/api/edit-proposals/${proposal.id}/${action}`, "POST");
    setProposal(updated);
    if (action === "accept") setDraft(await apiRequest<ResumeDraft>(`/api/jobs/${jobId}/draft`));
  }
  function togglePolishMethod(method: string) {
    setPolishMethods((current) => current.includes(method) ? current.filter((item) => item !== method) : [...current, method]);
  }
  async function runPolish(allowFabrication = false) {
    if (polishMethods.length === 0) { notify("请至少选择一种润色方式", "error"); return; }
    setBusy(true);
    try {
      const methods = allowFabrication ? ["add_experience"] : polishMethods;
      const result = await apiRequest<{ draft: ResumeDraft; added_real_count: number; fabricated: boolean; warnings: string[] }>(`/api/jobs/${jobId}/polish`, "POST", { methods, allow_fabrication: allowFabrication });
      setDraft(result.draft);
      if (!allowFabrication && polishMethods.includes("add_experience") && result.added_real_count === 0) {
        setShowFabricationRisk(true);
        return;
      }
      setShowFabricationRisk(false); setShowPolish(false);
      notify(result.fabricated ? result.warnings[0] : "简历润色已完成", result.fabricated ? "error" : "success");
    } catch (error) {
      notify(error instanceof Error ? error.message : "润色失败", "error");
    } finally {
      setBusy(false);
    }
  }

  async function startRecording() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      streamRef.current = stream; recorderRef.current = recorder; chunksRef.current = [];
      recorder.addEventListener("dataavailable", (event) => chunksRef.current.push(event.data));
      recorder.addEventListener("stop", async () => {
        setRecording(false);
        try {
          const recorded = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
          const wav = await convertRecordedAudioToWav(recorded);
          const result = await window.shadowDesktop?.transcribeAudio(await wav.arrayBuffer(), "audio/wav");
          if (result) setInstruction(result.text);
        } catch (error) { notify(error instanceof Error ? error.message : "转写失败，可继续使用文字输入", "error"); }
        finally { stream.getTracks().forEach((track) => track.stop()); streamRef.current = null; recorderRef.current = null; chunksRef.current = []; }
      });
      recorder.start(); setRecording(true);
    } catch { notify("无法使用麦克风，请检查权限；文字输入仍可使用", "error"); }
  }
  function stopRecording() { if (recorderRef.current?.state === "recording") recorderRef.current.stop(); }

  if (!config || !profile) return <main className="startup-state">正在加载简历工作台…</main>;
  const ordered = [...config.sections].sort((a, b) => a.order - b.order);
  return (
    <main className="workbench" aria-label="简历工作台">
      <header className="workbench-toolbar"><strong>影子简历助手 · 简历工作台</strong><label>模板 <select value={config.template} onChange={(event) => patchConfig({ template: event.target.value as ResumeConfig["template"] })}><option value="single_column">简洁单栏</option><option value="technical_double_column">技术型双栏</option></select></label><label>页数 <select value={config.page_target} onChange={(event) => patchConfig({ page_target: Number(event.target.value) as 1 | 2 })}><option value={1}>一页</option><option value={2}>两页</option></select></label><Button className="ghost" onClick={undo}>撤销</Button><Button className="ghost" onClick={redo}>重做</Button><Button disabled={busy} onClick={() => setShowGenerateOptions(true)}>生成简历</Button><Button className="secondary" disabled={!draft || busy} onClick={() => setShowPolish(true)}>润色</Button><Button className="ghost" onClick={saveDraft} disabled={!draft}>保存草稿</Button><Button className="secondary" onClick={saveVersion} disabled={!draft}>保存版本</Button><Button className="ghost" onClick={() => setShowVersions((value) => !value)}>历史版本</Button><Button className="ghost" onClick={() => setParagraphsExpanded((value) => !value)} disabled={!draft}>{paragraphsExpanded ? "收起段落" : "展开段落"}</Button><Button className="ghost" onClick={() => exportBoth(false)} disabled={!draft}>导出</Button><Button onClick={() => exportBoth(true)} disabled={!draft}>保存并导出</Button></header>
      <aside className="workbench-left"><h2>栏目与取舍</h2><p>拖动栏目可调整顺序；条数留空表示不限。</p>{ordered.map((section) => <article key={section.section_key} draggable onDragStart={() => { dragKey.current = section.section_key; }} onDragOver={(event) => event.preventDefault()} onDrop={() => dropSection(section.section_key)}><label className="check"><input type="checkbox" checked={section.enabled} onChange={(event) => updateSection(section.section_key, { enabled: event.target.checked })} />{section.title}</label><label className="field"><span>最多使用</span><input aria-label={`${section.title}最多使用`} type="number" min={1} max={20} placeholder="不限" value={section.max_entries ?? ""} onChange={(event) => updateSection(section.section_key, { max_entries: event.target.value ? Number(event.target.value) : null })} /></label>{config.template === "technical_double_column" && <select aria-label={`${section.title}栏位`} value={section.column} onChange={(event) => updateSection(section.section_key, { column: event.target.value as SectionConfig["column"] })}><option value="left">左栏</option><option value="right">右栏</option></select>}</article>)}<h3>经历取舍</h3>{profile.entries.map((entry) => <label className="entry-mode" key={entry.id}><span>{entry.title || "未命名经历"} · {entry.importance || 3}/5</span><select value={config.entry_modes[entry.id] || "ai_decide"} onChange={(event) => patchConfig({ entry_modes: { ...config.entry_modes, [entry.id]: event.target.value as ResumeConfig["entry_modes"][string] } })}><option value="ai_decide">AI 决定</option><option value="must_include">必须使用</option><option value="exclude_this_resume">不要用于这一份简历</option></select></label>)}</aside>
      <section className="workbench-canvas">{!draft ? <Card><EmptyState title="尚未生成草稿" description="完成左侧配置后生成简历。" /></Card> : <article className={`resume-preview ${config.template}`}><header><h1>{draft.document.personal_info.name || "姓名"}</h1><p>{draft.document.personal_info.contacts.join(" · ")}</p></header>{draft.document.sections.map((section) => <section className={`resume-section ${section.column || "full"}`} key={section.section_id}><h2>{section.title}</h2>{section.blocks.map((block) => <div key={block.block_id}><strong>{block.heading}</strong><small>{block.meta}</small>{block.paragraphs.map((paragraph) => <ResumeParagraphEditor key={paragraph.paragraph_id} label={`编辑${block.heading || section.title}`} text={paragraph.text} expanded={paragraphsExpanded} selected={selectedParagraph === paragraph.paragraph_id} onFocus={() => setSelectedParagraph(paragraph.paragraph_id)} onChange={(value) => editParagraph(paragraph.paragraph_id, value)} />)}</div>)}</section>)}</article>}</section>
      <aside className="workbench-right"><h2>{showVersions ? "历史版本" : "AI 修改助手"}</h2>{showVersions ? <div className="version-list">{versions.length === 0 ? <p>还没有主动保存的版本。</p> : versions.map((version) => <article key={version.id}><strong>{version.name}</strong><small>{new Date(version.created_at).toLocaleString()}</small>{version.notes && <p>{version.notes}</p>}<div className="actions"><Button className="ghost" onClick={() => editVersionMeta(version)}>改名/备注</Button><Button className="ghost" onClick={() => compareVersion(version)}>对比</Button><Button className="ghost" onClick={() => setRestoreTarget(version)}>恢复</Button><Button className="ghost" onClick={() => exportVersion(version)}>导出</Button><Button className="danger" onClick={() => deleteVersion(version)}>删除</Button></div></article>)}{comparison && <p>对比结果：{comparison.length ? `${comparison.length} 个内容块发生变化` : "没有变化"}</p>}</div> : <>{selectedParagraph ? <p className="selection-ready">已选择一个段落</p> : <p>先在画布中选择一段内容。</p>}<label className="field"><span>修改要求</span><textarea value={instruction} onChange={(event) => setInstruction(event.target.value)} placeholder="例如：写得更简洁，降低夸张程度" /></label><div className="actions"><Button className="secondary" onClick={recording ? stopRecording : startRecording}>{recording ? "停止录音" : "语音输入"}</Button><Button onClick={proposeEdit}>生成修改建议</Button></div><label className="field"><span>接受后保存到</span><select value={saveScope} onChange={(event) => setSaveScope(event.target.value)}><option value="current_resume">只用于当前简历</option><option value="also_profile">同时保存到个人资料库</option></select></label>{proposal && <Card title="修改前后对比"><div className="proposal-before"><small>修改前</small><p>{proposal.before_text}</p></div><div className="proposal-after"><small>修改后</small><p>{proposal.after_text}</p></div><p><strong>理由：</strong>{proposal.payload.reason}</p><p><strong>证据：</strong>{proposal.payload.evidence_ids.join("、")}</p>{proposal.status === "pending" ? <div className="actions"><Button onClick={() => decide("accept")}>接受</Button><Button className="danger" onClick={() => decide("reject")}>拒绝</Button><Button className="ghost" onClick={proposeEdit}>重新生成</Button></div> : <p className="save-state">已{proposal.status === "accepted" ? "接受" : "拒绝"}</p>}</Card>}</>}</aside>
      <Dialog open={showGenerateOptions} title="选择需要 AI 修改的栏目" onClose={() => setShowGenerateOptions(false)}><p>只勾选希望 AI 润色或重新排序的栏目。未勾选栏目会保留原有文字和条目顺序。</p><div className="polish-options">{ordered.filter((section) => section.enabled).map((section) => <label key={section.section_key}><input type="checkbox" checked={config.rewrite_sections.includes(section.section_key)} onChange={() => toggleRewriteSection(section.section_key)} />{section.title}<small>{config.rewrite_sections.includes(section.section_key) ? "AI 可以改写内容，并按岗位相关性调整本栏目条目顺序。" : "保持原有内容和条目顺序。"}</small></label>)}</div><div className="actions"><Button disabled={busy} onClick={runGenerate}>{busy ? "生成中…" : "按所选栏目生成"}</Button><Button className="ghost" disabled={busy} onClick={() => setShowGenerateOptions(false)}>取消</Button></div></Dialog>
      <Dialog open={factWarnings.length > 0} title="简历已生成，请核实 AI 补充内容" onClose={() => setFactWarnings([])}><p>整份简历已经生成并保存。以下内容没有在你的个人资料或原文中找到直接依据，可能是 AI 为了润色而补充的：</p><ul>{factWarnings.map((warning) => <li key={warning}>{warning}</li>)}</ul><p>你可以先保留这份简历，再直接修改相关内容；关闭或取消本提醒不会删除生成结果。</p><div className="actions"><Button onClick={() => setFactWarnings([])}>知道了，保留简历</Button><Button className="ghost" onClick={() => setFactWarnings([])}>取消提醒并保留简历</Button></div></Dialog>
      <Dialog open={showPolish} title="润色这份简历" onClose={() => setShowPolish(false)}><p>可多选。系统先使用你的真实资料，不会自动编造经历。</p><div className="polish-options"><label><input type="checkbox" checked={polishMethods.includes("expand_existing")} onChange={() => togglePolishMethod("expand_existing")} />扩写已有内容<small>在不新增事实的前提下，用 STAR/CAR 思路补足职责、行动和结果表达。</small></label><label><input type="checkbox" checked={polishMethods.includes("adjust_layout")} onChange={() => togglePolishMethod("adjust_layout")} />调整排版密度<small>适度调整字号、行距和段距，让页面更充实、均衡。</small></label><label><input type="checkbox" checked={polishMethods.includes("add_experience")} onChange={() => togglePolishMethod("add_experience")} />补充经历<small>优先加入个人资料库中尚未用于本简历的真实经历。</small></label></div><div className="actions"><Button disabled={busy} onClick={() => runPolish(false)}>开始润色</Button><Button className="ghost" onClick={() => setShowPolish(false)}>取消</Button></div></Dialog>
      <Dialog open={showFabricationRisk} title="确认 AI 编造风险" onClose={() => setShowFabricationRisk(false)}><p>个人资料库中的可用真实经历已经全部使用。继续后，AI 会加入一段没有真实资料依据的经历。</p><p className="risk-note">虚假经历可能在面试、背调或入职后被发现，并影响录用与个人信誉。请仅在你理解并愿意承担风险时继续。</p><div className="actions"><Button className="danger" disabled={busy} onClick={() => runPolish(true)}>我已了解风险，继续编造</Button><Button className="ghost" onClick={() => setShowFabricationRisk(false)}>不编造</Button></div></Dialog>
      <Dialog open={Boolean(restoreTarget)} title="恢复历史版本" onClose={() => setRestoreTarget(null)}><p>当前草稿可能有尚未保存为历史版本的修改。请选择：</p><div className="actions"><Button onClick={() => restoreTarget && restoreVersion(restoreTarget, true)}>先保存当前版本再恢复</Button><Button className="danger" onClick={() => restoreTarget && restoreVersion(restoreTarget, false)}>放弃当前修改并恢复</Button><Button className="ghost" onClick={() => setRestoreTarget(null)}>取消</Button></div></Dialog>
    </main>
  );
}
