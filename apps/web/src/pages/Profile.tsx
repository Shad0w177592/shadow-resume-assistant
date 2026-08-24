import { FormEvent, useEffect, useRef, useState } from "react";
import { apiRequest } from "../api";
import { Button, Card, EmptyState, TextInput } from "../components/ui";
import { useNotifications } from "../components/Notifications";
import type { Profile, ProfileEntry } from "../types";
import { Link } from "react-router-dom";

const categories = [
  ["education", "教育经历"], ["work", "工作经历"], ["internship", "实习经历"],
  ["project", "项目经历"], ["campus", "校园、社团及志愿经历"], ["skills", "专业技能"],
  ["awards", "证书与奖项"], ["other", "其他自定义经历或成果"],
];

export function ProfilePage() {
  const { notify } = useNotifications();
  const [profile, setProfile] = useState<Profile>({ id: "", display_name: "", personal_info: {}, entries: [] });
  const [loaded, setLoaded] = useState(false);
  const [saveState, setSaveState] = useState("等待填写");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [sectionKey, setSectionKey] = useState("project");
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [importance, setImportance] = useState(3);
  const [photoData, setPhotoData] = useState("");
  const entryFormRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!window.shadowDesktop) { setLoaded(true); return; }
    apiRequest<Profile>("/api/profile").then((value) => { setProfile(value); setLoaded(true); }).catch((error) => notify(error.message, "error"));
  }, [notify]);

  useEffect(() => {
    const fileId = profile.personal_info.photo_file_id;
    if (!fileId || !window.shadowDesktop) { setPhotoData(""); return; }
    apiRequest<{ data_url: string }>(`/api/profile/photo/${fileId}`)
      .then((result) => setPhotoData(result.data_url))
      .catch(() => setPhotoData(""));
  }, [profile.personal_info.photo_file_id]);

  useEffect(() => {
    if (!loaded || !window.shadowDesktop) return;
    setSaveState("保存中…");
    const timer = window.setTimeout(() => {
      apiRequest<Profile>("/api/profile", "PUT", { personal_info: profile.personal_info })
        .then(() => setSaveState("已自动保存"))
        .catch((error) => { setSaveState("保存失败"); notify(error.message, "error"); });
    }, 700);
    return () => window.clearTimeout(timer);
  }, [profile.personal_info, loaded, notify]);

  function changePersonal(key: string, value: string) {
    setProfile((current) => ({ ...current, personal_info: { ...current.personal_info, [key]: value } }));
  }

  async function submitEntry(event: FormEvent) {
    event.preventDefault();
    if (!content.trim() && !title.trim()) { notify("请至少填写标题或内容", "error"); return; }
    const body = { section_key: sectionKey, title: title || null, payload: { content }, importance };
    try {
      const saved = await apiRequest<ProfileEntry>(`/api/profile/entries${editingId ? `/${editingId}` : ""}`, editingId ? "PUT" : "POST", body);
      setProfile((current) => ({ ...current, entries: editingId ? current.entries.map((item) => item.id === saved.id ? saved : item) : [...current.entries, saved] }));
      setEditingId(null); setTitle(""); setContent(""); setImportance(3);
      notify("经历已保存", "success");
    } catch (error) { notify(error instanceof Error ? error.message : "保存失败", "error"); }
  }

  function edit(entry: ProfileEntry) {
    setEditingId(entry.id); setSectionKey(entry.section_key); setTitle(entry.title || "");
    setContent(String(entry.payload.content || ""));
    setImportance(entry.importance || 3);
    window.requestAnimationFrame(() => {
      entryFormRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      entryFormRef.current?.querySelector<HTMLInputElement>("input")?.focus();
    });
  }

  async function duplicate(entry: ProfileEntry) {
    const copied = await apiRequest<ProfileEntry>(`/api/profile/entries/${entry.id}/duplicate`, "POST");
    setProfile((current) => ({ ...current, entries: [...current.entries, copied] }));
  }

  async function remove(entry: ProfileEntry) {
    await apiRequest(`/api/profile/entries/${entry.id}`, "DELETE");
    setProfile((current) => ({ ...current, entries: current.entries.filter((item) => item.id !== entry.id) }));
  }

  async function choosePhoto() {
    const path = await window.shadowDesktop?.pickPhoto?.();
    if (!path) return;
    try {
      const result = await apiRequest<{ file_id: string; data_url: string }>(
        "/api/profile/photo/from-path", "POST", { path },
      );
      setPhotoData(result.data_url);
      changePersonal("photo_file_id", result.file_id);
      notify("照片已添加并将在导出时使用", "success");
    } catch (error) { notify(error instanceof Error ? error.message : "照片导入失败", "error"); }
  }

  return (
    <main className="page" aria-labelledby="page-title">
      <p className="eyebrow">影子简历助手</p><h1 id="page-title">个人资料</h1>
      <p className="description">所有栏目均为选填。没有的内容直接留空，不会阻止生成。 <Link to="/imports">从简历或作品集导入</Link></p>
      <Card title="个人信息">
        <div className="photo-picker">{photoData ? <img src={photoData} alt="个人照片预览" /> : <div className="photo-placeholder">暂无照片</div>}<div><Button className="ghost" onClick={choosePhoto}>{photoData ? "更换照片" : "添加照片"}</Button>{photoData && <Button className="ghost" onClick={() => { setPhotoData(""); changePersonal("photo_file_id", ""); }}>移除照片</Button>}<p>照片选填，仅保存在本机。</p></div></div>
        <div className="form-grid">
          <TextInput label="姓名（选填）" value={profile.personal_info.name || ""} onChange={(event) => changePersonal("name", event.target.value)} />
          <TextInput label="手机号（选填）" value={profile.personal_info.phone || ""} onChange={(event) => changePersonal("phone", event.target.value)} />
          <TextInput label="邮箱（选填）" value={profile.personal_info.email || ""} onChange={(event) => changePersonal("email", event.target.value)} />
          <TextInput label="所在城市（选填）" value={profile.personal_info.city || ""} onChange={(event) => changePersonal("city", event.target.value)} />
        </div>
        <label className="field"><span>自我介绍（选填）</span><textarea value={profile.personal_info.summary || ""} onChange={(event) => changePersonal("summary", event.target.value)} /></label>
        <p className="save-state" aria-live="polite">{saveState}</p>
      </Card>
      <div ref={entryFormRef} className="profile-entry-editor">
      <Card title={editingId ? "编辑经历" : "新增经历"}>
        <form onSubmit={submitEntry} className="entry-form">
          <label className="field"><span>栏目</span><select value={sectionKey} onChange={(event) => setSectionKey(event.target.value)}>{categories.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <TextInput label="标题（选填）" value={title} onChange={(event) => setTitle(event.target.value)} />
          <label className="field"><span>重要程度</span><select value={importance} onChange={(event) => setImportance(Number(event.target.value))}><option value={5}>5 - 最高</option><option value={4}>4 - 很重要</option><option value={3}>3 - 一般</option><option value={2}>2 - 较低</option><option value={1}>1 - 最低</option></select></label>
          <label className="field"><span>经历内容（选填，写你实际拥有的内容即可）</span><textarea value={content} onChange={(event) => setContent(event.target.value)} /></label>
          <div className="actions"><Button type="submit">{editingId ? "保存修改" : "新增经历"}</Button>{editingId && <Button type="button" className="secondary" onClick={() => setEditingId(null)}>取消</Button>}</div>
        </form>
      </Card>
      </div>
      <Card title="资料条目">
        {profile.entries.length === 0 ? <EmptyState title="还没有经历" description="只填写你实际拥有的内容；缺少成果、技能或时间都可以留空。" /> : <ul className="record-list">{profile.entries.map((entry) => <li key={entry.id}><div><strong>{entry.title || "未命名经历"}</strong><span>{categories.find(([key]) => key === entry.section_key)?.[1] || entry.section_key} · 重要程度：{entry.importance || 3}/5</span></div><div className="inline-actions"><Button className="ghost" onClick={() => edit(entry)}>编辑</Button><Button className="ghost" onClick={() => duplicate(entry)}>复制</Button><Button className="danger" onClick={() => remove(entry)}>删除</Button></div></li>)}</ul>}
      </Card>
    </main>
  );
}
