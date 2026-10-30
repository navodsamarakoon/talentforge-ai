export type User = {
  id: string;
  email: string;
  full_name: string;
  role: "recruiter" | "candidate";
  organization_id: string | null;
};

export type JobOpening = {
  id: string;
  organization_id: string;
  title: string;
  description: string;
  employment_type: "internship" | "full-time" | "part-time";
  location: string;
  status: "draft" | "published" | "closed";
  created_at: string;
};

export type JobApplication = {
  id: string;
  job_opening_id: string;
  job_title?: string;
  original_cv_filename: string;
  status: "submitted" | "screening" | "rejected" | "selected";
  submitted_at: string;
};

export type TestCase = {
  input_args: unknown[];
  expected_output: unknown;
  is_hidden: boolean;
};

export type Question = {
  id: string;
  position: number;
  title: string;
  prompt: string;
  function_name: string;
  starter_code: string;
  test_cases: TestCase[];
};

export type Assessment = {
  id: string;
  title: string;
  role: string;
  instructions: string;
  time_limit_minutes: number;
  allow_multiple_attempts: boolean;
  is_published: boolean;
  is_archived: boolean;
  has_candidate_records: boolean;
  created_at: string;
  published_at: string | null;
  questions: Question[];
};

export type Attempt = {
  id: string;
  assessment_id: string;
  started_at: string;
  deadline_at: string;
  completed_at: string | null;
  server_time: string;
  submissions?: SubmissionStatus[];
  assessment: Assessment;
};

export type SubmissionStatus = {
  id: string;
  question_id: string;
  execution_status: string;
  evaluation_status: string;
};

export type Report = {
  submission_id: string;
  candidate_id: string;
  candidate_email: string;
  candidate_name: string;
  assessment_id: string;
  question_title?: string;
  overall_score: number | null;
  criteria: Record<string, { score: number; evidence: string }> | null;
  strengths: string[] | null;
  weaknesses: string[] | null;
  final_summary: string | null;
  execution_status: string;
  execution_results: { passed: boolean; status: string; message: string }[];
  evaluation_status: string;
  limitations: string;
};

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000/api";

export function saveAuth(token: string, user: User) {
  window.localStorage.setItem("talentforge-token", token);
  window.localStorage.setItem("talentforge-user", JSON.stringify(user));
}

export function clearAuth() {
  window.localStorage.removeItem("talentforge-token");
  window.localStorage.removeItem("talentforge-user");
}

export function getUser(): User | null {
  const value = window.localStorage.getItem("talentforge-user");
  if (!value) return null;
  try {
    return JSON.parse(value) as User;
  } catch {
    clearAuth();
    return null;
  }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = window.localStorage.getItem("talentforge-token");
  const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      ...(options.body && !isFormData ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null) as {
      detail?: string | { message?: string } | { msg?: string; loc?: (string | number)[] }[];
    } | null;
    const detail = body?.detail;
    const message = typeof detail === "string"
      ? detail
      : Array.isArray(detail)
        ? detail.map(item => {
          const location = item.loc?.filter(part => part !== "body").join(".");
          return location ? `${location}: ${item.msg ?? "Invalid value."}` : item.msg ?? "Invalid value.";
        }).join(" ")
        : detail?.message;
    throw new Error(message ? `Request failed (${response.status}): ${message}` : `Request failed (${response.status}).`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
