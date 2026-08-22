export type ProfileEntry = {
  id: string;
  section_key: string;
  title: string | null;
  payload: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type Profile = {
  id: string;
  display_name: string;
  personal_info: Record<string, string>;
  entries: ProfileEntry[];
};

export type Job = {
  id: string;
  company: string | null;
  title: string | null;
  jd_text: string;
  notes: string | null;
  status: string;
  updated_at: string;
};

export type ResumeDraft = {
  id: string;
  job_target_id: string;
  document: {
    personal_info: { name: string; headline: string; contacts: string[] };
    sections: Array<{
      section_id: string;
      section_key: string;
      title: string;
      order: number;
      column: string;
      blocks: Array<{
        block_id: string;
        heading: string;
        meta: string;
        paragraphs: Array<{ paragraph_id: string; text: string; source_entry_ids: string[] }>;
      }>;
    }>;
  };
};
