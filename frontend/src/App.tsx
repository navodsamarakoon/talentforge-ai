import { Fragment, lazy, Suspense, type FormEvent, type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import Editor from "@monaco-editor/react";
import { loader } from "@monaco-editor/react";
import { Archive, ArrowRight, BriefcaseBusiness, Check, CircleAlert, Clock3, Code2, Copy, FilePlus2, LogOut, Plus, ShieldCheck, Users, X } from "lucide-react";
import { Link, Navigate, Route, Routes, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, Assessment, Attempt, clearAuth, getUser, Report, saveAuth, SubmissionStatus, User } from "./api";

const RobotTestPage = lazy(() => import("./RobotTestPage"));
const SplineRobot = lazy(() => import("./SplineRobot"));

loader.config({ paths: { vs: "/vs" } });

function ErrorMessage({ children }: { children: string }) {
  return <div className="error-banner" role="alert"><CircleAlert size={17} />{children}</div>;
}

function Busy({ label = "Loading…" }: { label?: string }) {
  return <div className="loading"><span className="spinner" />{label}</div>;
}

function Protected({ role, children }: { role?: User["role"]; children: ReactNode }) {
  const user = getUser();
  if (!user) return <Navigate to="/login" replace />;
  if (role && user.role !== role) return <Navigate to={user.role === "recruiter" ? "/recruiter" : "/candidate"} replace />;
  return children;
}

function Shell({ user, children, pageClassName = "" }: { user?: User | null; children: ReactNode; pageClassName?: string }) {
  const navigate = useNavigate();
  const logout = async () => {
    try { if (user) await api("/auth/logout", { method: "POST" }); } finally {
      clearAuth();
      navigate("/login");
    }
  };
  return <div className="app-shell">
    <header className="topbar">
      <Link to={user?.role === "candidate" ? "/candidate" : "/recruiter"} className="brand"><img className="brand-icon" src="/talentforge-mark.svg" alt="" />talentforge<span className="brand-ai">AI</span></Link>
      {user && <nav className="top-nav">
        {user.role === "recruiter" ? <Link to="/recruiter">Workspace</Link> : <Link to="/candidate">My assessments</Link>}
        <div className="user-menu"><span className="avatar">{user.full_name.slice(0, 1).toUpperCase()}</span><span className="user-name">{user.full_name}</span><button className="icon-button" aria-label="Log out" onClick={() => void logout()}><LogOut size={16} /></button></div>
      </nav>}
    </header>
    <main className={`page ${pageClassName}`.trim()}>{children}</main>
    <footer className="footer"><span>TalentForge AI</span><span>Technical assessment workspace</span></footer>
  </div>;
}

function AuthPage({ mode }: { mode: "login" | "register" }) {
  const navigate = useNavigate();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [organization, setOrganization] = useState("");
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      const response = await api<{ access_token: string; user: User }>(mode === "login" ? "/auth/login" : "/auth/register", {
        method: "POST",
        body: JSON.stringify(mode === "login" ? { email, password } : { email, password, full_name: name, organization_name: organization }),
      });
      saveAuth(response.access_token, response.user);
      navigate(response.user.role === "recruiter" ? "/recruiter" : "/candidate");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Could not authenticate."); }
    finally { setBusy(false); }
  };
  return <Shell pageClassName={mode === "login" ? "auth-page auth-login-page" : "auth-page"}><div className="auth-layout auth-composition-layout">
    <section className="auth-story">
      <span className="eyebrow"><span className="eyebrow-dot" />Assessment, with evidence</span>
      <h1>Find the thinking<br />behind the code.</h1>
      <p>Run structured technical assessments with a secure coding workspace and evidence-based evaluation.</p>
      <div className="story-points"><div><span><ShieldCheck size={17} /></span><div><b>Fair by design</b><small>Consistent questions and test coverage.</small></div></div><div><span><Code2 size={17} /></span><div><b>Built for real work</b><small>Candidates solve in a focused Python workspace.</small></div></div></div>
      <div className="auth-decoration"><div className="decor-line">def evaluate(solution):</div><div className="decor-line indent">return evidence, not guesswork</div></div>
    </section>
    <div className="auth-robot-stage" aria-label="TalentForge AI animated robot">
      <Suspense fallback={<div className="auth-robot-fallback" role="status">Loading robot…</div>}><SplineRobot /></Suspense>
    </div>
    <section className="auth-card">
      <div className="card-mark"><BriefcaseBusiness size={20} /></div>
      <h2>{mode === "login" ? "Welcome back" : "Create your workspace"}</h2>
      <p className="muted">{mode === "login" ? "Sign in to continue to TalentForge." : "Start assessing candidates with your team."}</p>
      {error && <ErrorMessage>{error}</ErrorMessage>}
      <form onSubmit={submit} className="form-stack">
        {mode === "register" && <><label>Full name<input required maxLength={160} value={name} onChange={e => setName(e.target.value)} placeholder="Your name" /></label><label>Organization<input required maxLength={160} value={organization} onChange={e => setOrganization(e.target.value)} placeholder="Organization name" /></label></>}
        <label>Work email<input type="email" required value={email} onChange={e => setEmail(e.target.value)} placeholder="you@company.com" /></label>
        <label>Password<input type="password" required minLength={mode === "register" ? 12 : 1} value={password} onChange={e => setPassword(e.target.value)} placeholder={mode === "register" ? "At least 12 characters" : "Your password"} /></label>
        <button className="button primary full" disabled={busy}>{busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create recruiter account"}<ArrowRight size={16} /></button>
      </form>
      <p className="auth-switch">{mode === "login" ? "New to TalentForge?" : "Already have an account?"} <Link to={mode === "login" ? "/register" : "/login"}>{mode === "login" ? "Create an account" : "Sign in"}</Link></p>
    </section>
  </div></Shell>;
}

function AcceptInvitation() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const token = params.get("token") ?? "";
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const result = await api<{ access_token: string; user: User }>("/invitations/accept", { method: "POST", body: JSON.stringify({ token, full_name: name, password }) });
      saveAuth(result.access_token, result.user); navigate("/candidate");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Could not accept invitation."); }
    finally { setBusy(false); }
  };
  return <Shell><div className="auth-card invite-card"><div className="card-mark"><Users size={20} /></div><h2>Accept your invitation</h2><p className="muted">Create a candidate account to continue. This invitation is single-use and expires.</p>{!token && <ErrorMessage>The invitation link is missing its token.</ErrorMessage>}{error && <ErrorMessage>{error}</ErrorMessage>}
    <form onSubmit={submit} className="form-stack"><label>Full name<input required value={name} onChange={e => setName(e.target.value)} /></label><label>Create password<input type="password" required minLength={12} value={password} onChange={e => setPassword(e.target.value)} /></label><button disabled={busy || !token} className="button primary full">{busy ? "Accepting…" : "Accept invitation"}<ArrowRight size={16} /></button></form>
  </div></Shell>;
}

function RecruiterHome() {
  const [assessments, setAssessments] = useState<Assessment[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [title, setTitle] = useState("");
  const [role, setRole] = useState("Software Engineer");
  const [instructions, setInstructions] = useState("");
  const [limit, setLimit] = useState(60);
  const [saving, setSaving] = useState(false);
  const [pendingAction, setPendingAction] = useState<{ id: string; action: "delete" | "archive" | "unarchive" } | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [showArchived, setShowArchived] = useState(false);
  const loadSequence = useRef(0);
  const load = useCallback(async () => {
    const sequence = ++loadSequence.current;
    setError(""); setAssessments([]); setLoading(true);
    try {
      const rows = await api<Assessment[]>(showArchived ? "/assessments?archived=true" : "/assessments");
      if (sequence === loadSequence.current) setAssessments(rows);
    } catch (caught) {
      if (sequence === loadSequence.current) setError(caught instanceof Error ? caught.message : "Unable to load assessments.");
    } finally {
      if (sequence === loadSequence.current) setLoading(false);
    }
  }, [showArchived]);
  useEffect(() => { void load(); }, [load]);
  const create = async (event: FormEvent) => {
    event.preventDefault();
    if (!title.trim()) { setError("Enter an assessment title."); return; }
    if (!Number.isInteger(limit) || limit < 5 || limit > 480) { setError("Time limit must be between 5 and 480 minutes."); return; }
    setSaving(true); setError(""); setNotice("");
    try {
      const item = await api<Assessment>("/assessments", { method: "POST", body: JSON.stringify({ title: title.trim(), role, instructions, time_limit_minutes: limit, allow_multiple_attempts: false }) });
      setAssessments(current => [item, ...current]); setShowCreate(false); setTitle("");
      setNotice(`Assessment "${item.title}" was created.`);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Could not create assessment."); }
    finally { setSaving(false); }
  };
  const deleteAssessment = async (item: Assessment) => {
    if (!window.confirm(`Delete "${item.title}"? This permanently removes the assessment. Assessments with candidate invitations or attempts cannot be deleted.`)) return;
    setPendingAction({ id: item.id, action: "delete" }); setError(""); setNotice("");
    try {
      await api<void>(`/assessments/${item.id}`, { method: "DELETE" });
      setAssessments(current => current.filter(assessment => assessment.id !== item.id));
      setNotice(`Assessment "${item.title}" was deleted.`);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Could not delete assessment."); }
    finally { setPendingAction(null); }
  };
  const archiveAssessment = async (item: Assessment) => {
    if (!window.confirm(`Archive "${item.title}"? It will be hidden from the active workspace while candidate invitations, attempts, submissions, and reports are preserved.`)) return;
    setPendingAction({ id: item.id, action: "archive" }); setError(""); setNotice("");
    try {
      const result = await api<Assessment>(`/assessments/${item.id}/archive`, { method: "POST" });
      if (!result.is_archived) throw new Error("The server did not confirm that the assessment was archived.");
      setAssessments(current => current.filter(assessment => assessment.id !== item.id));
      setNotice(`Assessment "${item.title}" was archived. Candidate history is preserved.`);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Could not archive assessment."); }
    finally { setPendingAction(null); }
  };
  const unarchiveAssessment = async (item: Assessment) => {
    setPendingAction({ id: item.id, action: "unarchive" }); setError(""); setNotice("");
    try {
      const result = await api<Assessment>(`/assessments/${item.id}/unarchive`, { method: "POST" });
      if (result.is_archived) throw new Error("The server did not confirm that the assessment was restored.");
      setAssessments(current => current.filter(assessment => assessment.id !== item.id));
      setNotice(`Assessment "${item.title}" was restored to the active workspace.`);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Could not restore assessment."); }
    finally { setPendingAction(null); }
  };
  const filteredAssessments = assessments.filter(item => {
    const matchesSearch = `${item.title} ${item.role} ${item.instructions}`.toLowerCase().includes(search.trim().toLowerCase());
    const matchesStatus = statusFilter === "all" || (statusFilter === "published" ? item.is_published : !item.is_published);
    return matchesSearch && matchesStatus;
  });
  const published = assessments.filter(item => item.is_published).length;
  const showAssessmentEmpty = !loading && assessments.length === 0 && !error;
  return <Shell user={getUser()}><div className="page-heading"><div><span className="eyebrow">Recruiter workspace</span><h1>Good work starts with a fair assessment.</h1><p>Build coding assessments, invite candidates, and compare evidence.</p></div>{!showArchived && <button className="button primary" onClick={() => setShowCreate(v => !v)}><Plus size={17} />New assessment</button>}</div>
    {error && <ErrorMessage>{error}</ErrorMessage>}{notice && <div className="success-banner" role="status">{notice}</div>}
    {!showArchived && <div className="stats-grid"><div className="stat-card"><div className="stat-icon blue"><FilePlus2 size={18} /></div><span>Active assessments</span><b>{assessments.length}</b><small>Across your organization</small></div><div className="stat-card"><div className="stat-icon green"><Check size={18} /></div><span>Published</span><b>{published}</b><small>Ready for candidates</small></div><div className="stat-card"><div className="stat-icon violet"><Users size={18} /></div><span>Assessment format</span><b>Python</b><small>Software engineering roles</small></div></div>}
    {!showArchived && showCreate && <section className="panel create-panel"><div className="section-title"><div><span className="eyebrow">New assessment</span><h2>Set up the basics</h2></div><button className="icon-button" aria-label="Close" onClick={() => setShowCreate(false)}><X size={18} /></button></div><form className="form-grid" onSubmit={create}><label>Assessment title<input required minLength={1} maxLength={200} value={title} onChange={e => setTitle(e.target.value)} placeholder="e.g. Backend Engineering — Algorithms" /></label><label>Role<select value={role} onChange={e => setRole(e.target.value)}><option>Software Engineer</option><option>Software Engineering Intern</option></select></label><label>Time limit (minutes)<input required type="number" min={5} max={480} value={limit} onChange={e => setLimit(Number(e.target.value))} /></label><label className="span-two">Candidate instructions<textarea maxLength={20000} value={instructions} onChange={e => setInstructions(e.target.value)} placeholder="Provide context and rules for the assessment." /></label><div className="span-two form-actions"><button type="button" className="button secondary" onClick={() => setShowCreate(false)}>Cancel</button><button className="button primary" disabled={saving}>{saving ? "Creating…" : "Create draft"}<ArrowRight size={15} /></button></div></form></section>}
    <div className="section-title list-header"><div><span className="eyebrow">Your organization</span><h2>{showArchived ? "Archived assessments" : "Active assessments"} <span className="count">{assessments.length}</span></h2></div><div className="assessment-view-switch" role="group" aria-label="Assessment workspace view"><button type="button" className={`button ${showArchived ? "secondary" : "primary"}`} aria-pressed={!showArchived} onClick={() => { setShowArchived(false); setLoading(true); }}>Active</button><button type="button" className={`button ${showArchived ? "primary" : "secondary"}`} aria-pressed={showArchived} onClick={() => { setShowArchived(true); setLoading(true); }}><Archive size={15} />Archived</button></div></div>
    {loading ? <Busy /> : error && assessments.length === 0 ? <div className="empty-state"><h3>Assessments could not be loaded.</h3><button className="button secondary" onClick={() => void load()}>Try again</button></div> : showAssessmentEmpty ? <div className="empty-state">{showArchived ? <><h3>No archived assessments.</h3><p>Assessments you archive will appear here. Their invitations and candidate history remain preserved.</p></> : <><div className="empty-icon"><Code2 /></div><h3>Your first assessment is one step away.</h3><p>Create a draft, add Python questions and hidden test cases, then publish it.</p><button className="button primary" onClick={() => setShowCreate(true)}><Plus size={16} />Create an assessment</button></>}</div> : <><div className="assessment-filters"><label>Search assessments<input aria-label="Search assessments" type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="Search title, role, or instructions" /></label><label>Status<select aria-label="Filter by status" value={statusFilter} onChange={event => setStatusFilter(event.target.value)}><option value="all">All statuses</option><option value="draft">Draft</option><option value="published">Published</option></select></label></div>{filteredAssessments.length === 0 ? <div className="empty-state"><h3>No matching assessments.</h3><p>Try a different search or status filter.</p></div> : <div className="assessment-list">{filteredAssessments.map(item => <article className="assessment-card" key={item.id}><Link to={`/assessments/${item.id}`} className="assessment-card-link"><div className="assessment-symbol"><Code2 size={19} /></div><div className="assessment-main"><div className="title-line"><h3>{item.title}</h3><span className={`status ${item.is_archived ? "archived" : item.is_published ? "published" : "draft"}`}><i />{item.is_archived ? "Archived" : item.is_published ? "Published" : "Draft"}</span></div><p>{item.role} <span className="dot-sep">·</span> {item.questions.length} {item.questions.length === 1 ? "question" : "questions"} <span className="dot-sep">·</span> {item.time_limit_minutes} min <span className="dot-sep">·</span> Created {new Date(item.created_at).toLocaleDateString()}</p><p className="assessment-description">{item.instructions || "No candidate instructions provided."}</p></div></Link><div className="assessment-actions">{item.is_archived && <button className="button secondary" disabled={pendingAction !== null} onClick={() => void unarchiveAssessment(item)}>{pendingAction?.id === item.id && pendingAction.action === "unarchive" ? "Restoring…" : "Restore"}</button>}{item.has_candidate_records ? !item.is_archived && <button className="button secondary" disabled={pendingAction !== null} onClick={() => void archiveAssessment(item)}>{pendingAction?.id === item.id && pendingAction.action === "archive" ? "Archiving…" : "Archive"}</button> : <button className="button secondary danger-button" disabled={pendingAction !== null} onClick={() => void deleteAssessment(item)}>{pendingAction?.id === item.id && pendingAction.action === "delete" ? "Deleting…" : "Delete"}</button>}</div></article>)}</div>}</>}
  </Shell>;
}

function QuestionEditor({ assessment, selectedId, onSelectedId, onSaved }: {
  assessment: Assessment;
  selectedId: string;
  onSelectedId: (questionId: string) => void;
  onSaved: (assessment: Assessment) => void;
}) {
  const [position, setPosition] = useState(assessment.questions.length);
  const [title, setTitle] = useState("");
  const [prompt, setPrompt] = useState("");
  const [functionName, setFunctionName] = useState("solve");
  const [starter, setStarter] = useState("def solve():\n    pass\n");
  const [testCases, setTestCases] = useState(JSON.stringify([
    { input_args: [1, 2], expected_output: 3, is_hidden: false },
    { input_args: [2, 4], expected_output: 6, is_hidden: true },
  ], null, 2));
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const question = assessment.questions.find(item => item.id === selectedId);
    setPosition(question?.position ?? assessment.questions.length);
    setTitle(question?.title ?? "");
    setPrompt(question?.prompt ?? "");
    setFunctionName(question?.function_name ?? "solve");
    setStarter(question?.starter_code ?? "def solve():\n    pass\n");
    setTestCases(JSON.stringify(question?.test_cases.map(item => ({
      input_args: item.input_args,
      expected_output: item.expected_output,
      is_hidden: item.is_hidden,
    })) ?? [
      { input_args: [1, 2], expected_output: 3, is_hidden: false },
      { input_args: [2, 4], expected_output: 6, is_hidden: true },
    ], null, 2));
  }, [assessment.questions, selectedId]);
  const save = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError(""); setNotice("");
    try {
      const payload = {
        position, title, prompt, function_name: functionName, starter_code: starter,
        test_cases: JSON.parse(testCases) as { input_args: unknown[]; expected_output: unknown; is_hidden: boolean }[],
      };
      const updated = await api<Assessment>(selectedId
        ? `/assessments/${assessment.id}/questions/${selectedId}`
        : `/assessments/${assessment.id}/questions`, {
        method: selectedId ? "PATCH" : "POST",
        body: JSON.stringify(payload),
      });
      onSaved(updated);
      setNotice(selectedId ? "Question changes saved." : "Question added.");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Could not save question."); }
    finally { setBusy(false); }
  };
  const cancelEdit = () => {
    onSelectedId("");
    setError("");
    setNotice("");
  };
  return <section id="question-editor" className="panel"><div className="section-title"><div><span className="eyebrow">Question builder</span><h2>{selectedId ? "Edit coding question" : "Add a Python coding question"}</h2></div></div>{error && <ErrorMessage>{error}</ErrorMessage>}{notice && <div className="success-banner" role="status">{notice}</div>}
    <form onSubmit={save} className="form-grid">
      <label className="span-two">Question to edit<select value={selectedId} onChange={event => onSelectedId(event.target.value)}><option value="">Create a new question</option>{assessment.questions.map(question => <option key={question.id} value={question.id}>{question.position + 1}. {question.title}</option>)}</select></label>
      <label>Question title<input required value={title} onChange={e => setTitle(e.target.value)} placeholder="e.g. Add two numbers" /></label>
      <label>Function name<input required pattern="[A-Za-z_][A-Za-z0-9_]*" value={functionName} onChange={e => setFunctionName(e.target.value)} /></label>
      <label>Question order<input type="number" min={0} value={position} onChange={e => setPosition(Number(e.target.value))} /></label>
      <label className="span-two">Problem statement<textarea required rows={4} value={prompt} onChange={e => setPrompt(e.target.value)} placeholder="Describe the problem and constraints." /></label>
      <label className="span-two">Python starter code<textarea className="code-input" rows={5} value={starter} onChange={e => setStarter(e.target.value)} /></label>
      <label className="span-two">Test cases (JSON)<textarea className="code-input" rows={9} required value={testCases} onChange={e => setTestCases(e.target.value)} aria-describedby="test-case-help" /><small id="test-case-help" className="field-help">Each item uses input_args, expected_output, and is_hidden. Keep at least one visible and one hidden case to publish.</small></label>
      <div className="span-two form-actions">{selectedId && <button type="button" className="button secondary" disabled={busy} onClick={cancelEdit}>Cancel</button>}<button disabled={busy} className="button primary">{busy ? "Saving…" : selectedId ? "Save question changes" : "Add question"}<Check size={15} /></button></div>
    </form>
  </section>;
}

function AssessmentSettings({ assessment, onSaved }: { assessment: Assessment; onSaved: (assessment: Assessment) => void }) {
  const [title, setTitle] = useState(assessment.title);
  const [role, setRole] = useState(assessment.role);
  const [instructions, setInstructions] = useState(assessment.instructions);
  const [timeLimit, setTimeLimit] = useState(assessment.time_limit_minutes);
  const [multipleAttempts, setMultipleAttempts] = useState(assessment.allow_multiple_attempts);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setTitle(assessment.title);
    setRole(assessment.role);
    setInstructions(assessment.instructions);
    setTimeLimit(assessment.time_limit_minutes);
    setMultipleAttempts(assessment.allow_multiple_attempts);
  }, [assessment.id, assessment.title, assessment.role, assessment.instructions, assessment.time_limit_minutes, assessment.allow_multiple_attempts]);
  const save = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError(""); setNotice("");
    try {
      const updated = await api<Assessment>(`/assessments/${assessment.id}`, { method: "PATCH", body: JSON.stringify({
        title, role, instructions, time_limit_minutes: timeLimit, allow_multiple_attempts: multipleAttempts,
      }) });
      onSaved(updated);
      setTitle(updated.title);
      setRole(updated.role);
      setInstructions(updated.instructions);
      setTimeLimit(updated.time_limit_minutes);
      setMultipleAttempts(updated.allow_multiple_attempts);
      setNotice("Assessment details saved.");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Could not update assessment."); }
    finally { setBusy(false); }
  };
  return <section className="panel"><div className="section-title"><div><span className="eyebrow">Draft settings</span><h2>Edit assessment details</h2></div></div>{error && <ErrorMessage>{error}</ErrorMessage>}{notice && <div className="success-banner" role="status">{notice}</div>}
    <form onSubmit={save} className="form-grid"><label>Title<input required value={title} onChange={event => setTitle(event.target.value)} /></label><label>Role<select value={role} onChange={event => setRole(event.target.value)}><option>Software Engineer</option><option>Software Engineering Intern</option></select></label><label>Time limit in minutes<input type="number" min={5} max={480} value={timeLimit} onChange={event => setTimeLimit(Number(event.target.value))} /></label><label className="checkbox-label"><input type="checkbox" checked={multipleAttempts} onChange={event => setMultipleAttempts(event.target.checked)} />Allow another attempt after an attempt is completed</label><label className="span-two">Instructions<textarea value={instructions} onChange={event => setInstructions(event.target.value)} /></label><div className="span-two form-actions"><button disabled={busy} className="button primary">{busy ? "Saving…" : "Save assessment details"}</button></div></form>
  </section>;
}

function AssessmentDetail() {
  const { id = "" } = useParams();
  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const [selectedQuestionId, setSelectedQuestionId] = useState("");
  const [reports, setReports] = useState<Report[]>([]);
  const [invitations, setInvitations] = useState<{ id: string; email: string; expires_at: string; revoked_at: string | null; accepted_at: string | null }[]>([]);
  const [email, setEmail] = useState("");
  const [inviteUrl, setInviteUrl] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try {
      const [item, reportRows] = await Promise.all([api<Assessment>(`/assessments/${id}`), api<Report[]>(`/assessments/${id}/compare`)]);
      setAssessment(item); setReports(reportRows);
      setInvitations(item.is_published ? await api<{ id: string; email: string; expires_at: string; revoked_at: string | null; accepted_at: string | null }[]>(`/assessments/${id}/invitations`) : []);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to load assessment."); }
    finally { setLoading(false); }
  }, [id]);
  useEffect(() => { void load(); }, [load]);
  const publish = async () => { setBusy(true); setError(""); try { await api(`/assessments/${id}/publish`, { method: "POST" }); await load(); } catch (caught) { setError(caught instanceof Error ? caught.message : "Could not publish."); } finally { setBusy(false); } };
  const invite = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const result = await api<{ id: string; email: string; expires_at: string; revoked_at: string | null; accepted_at: string | null; invitation_url: string }>(`/assessments/${id}/invitations`, { method: "POST", body: JSON.stringify({ email }) });
      setInviteUrl(new URL(result.invitation_url, window.location.origin).href);
      setInvitations(current => [result, ...current]);
      setEmail("");
    }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Could not create invitation."); } finally { setBusy(false); }
  };
  const revokeInvitation = async (invitationId: string) => {
    setBusy(true); setError("");
    try {
      await api(`/assessments/${id}/invitations/${invitationId}/revoke`, { method: "POST" });
      setInvitations(current => current.map(item => item.id === invitationId ? { ...item, revoked_at: new Date().toISOString() } : item));
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Could not revoke invitation."); }
    finally { setBusy(false); }
  };
  if (loading) return <Shell user={getUser()}><Busy /></Shell>;
  if (!assessment) return <Shell user={getUser()}><ErrorMessage>{error || "Assessment not found."}</ErrorMessage></Shell>;
  return <Shell user={getUser()}><Link to="/recruiter" className="back-link">← All assessments</Link><div className="detail-heading"><div><div className="title-line"><h1>{assessment.title}</h1><span className={`status ${assessment.is_archived ? "archived" : assessment.is_published ? "published" : "draft"}`}><i />{assessment.is_archived ? "Archived" : assessment.is_published ? "Published" : "Draft"}</span></div><p>{assessment.role} <span className="dot-sep">·</span> {assessment.time_limit_minutes} min <span className="dot-sep">·</span> {assessment.questions.length} questions</p></div>{!assessment.is_published && !assessment.is_archived && <button className="button primary" onClick={() => void publish()} disabled={busy}><ShieldCheck size={16} />Publish assessment</button>}</div>
    {error && <ErrorMessage>{error}</ErrorMessage>}
    {!assessment.is_published && !assessment.is_archived && <><AssessmentSettings assessment={assessment} onSaved={setAssessment} /><QuestionEditor assessment={assessment} selectedId={selectedQuestionId} onSelectedId={setSelectedQuestionId} onSaved={setAssessment} /></>}
    {assessment.is_archived && <div className="success-banner" role="status">This assessment is archived. Candidate invitations, attempts, submissions, and reports are preserved.</div>}
    <section className="panel"><div className="section-title"><div><span className="eyebrow">Assessment content</span><h2>Coding questions</h2></div></div>{assessment.questions.length === 0 ? <p className="muted">No questions yet. Add a question with sample and hidden test cases.</p> : <div className="question-list">{assessment.questions.map((question, index) => assessment.is_published || assessment.is_archived ? <article className="question-row" key={question.id}><div className="question-number">{String(index + 1).padStart(2, "0")}</div><div><h3>{question.title}</h3><p>{question.function_name} · {question.test_cases.filter(item => !item.is_hidden).length} sample · {question.test_cases.filter(item => item.is_hidden).length} hidden cases</p></div></article> : <button type="button" className="question-row question-row-button" key={question.id} aria-label={`Edit question ${question.title}`} onClick={() => { setSelectedQuestionId(question.id); document.getElementById("question-editor")?.scrollIntoView?.({ behavior: "smooth", block: "start" }); }}><div className="question-number">{String(index + 1).padStart(2, "0")}</div><div><h3>{question.title}</h3><p>{question.function_name} · {question.test_cases.filter(item => !item.is_hidden).length} sample · {question.test_cases.filter(item => item.is_hidden).length} hidden cases</p></div></button>)}</div>}</section>
    {assessment.is_published && <section className="panel invite-panel"><div className="section-title"><div><span className="eyebrow">{assessment.is_archived ? "Candidate history" : "Candidate access"}</span><h2>{assessment.is_archived ? "Preserved candidate invitations" : "Invite a candidate"}</h2></div></div>{!assessment.is_archived && <><form className="invite-form" onSubmit={invite}><input aria-label="Candidate email" type="email" required placeholder="candidate@email.com" value={email} onChange={e => setEmail(e.target.value)} /><button className="button primary" disabled={busy}><Plus size={16} />Create secure invite</button></form>{inviteUrl && <div className="invite-link"><div><small>One-time invitation link — copy and share with the intended candidate.</small><a href={inviteUrl}>{inviteUrl}</a></div><button className="button secondary" onClick={() => void navigator.clipboard.writeText(inviteUrl)}><Copy size={15} />Copy</button></div>}</>}
      {invitations.length > 0 && <div className="table-wrap"><table><thead><tr><th>Candidate</th><th>Expires</th><th>Status</th><th /></tr></thead><tbody>{invitations.map(invitation => <tr key={invitation.id}><td>{invitation.email}</td><td>{new Date(invitation.expires_at).toLocaleString()}</td><td>{invitation.revoked_at ? "Revoked" : invitation.accepted_at ? "Accepted" : "Pending"}</td><td>{!assessment.is_archived && !invitation.revoked_at && <button className="button secondary" disabled={busy} onClick={() => void revokeInvitation(invitation.id)}>Revoke</button>}</td></tr>)}</tbody></table></div>}
    </section>}
    <section className="panel"><div className="section-title"><div><span className="eyebrow">Evidence and feedback</span><h2>Candidate comparison</h2></div><span className="count">{reports.length}</span></div>{reports.length === 0 ? <p className="muted">Candidate submissions will appear here after they complete questions.</p> : <div className="table-wrap"><table><thead><tr><th>Candidate</th><th>Question</th><th>Tests</th><th>AI evaluation</th><th>Score</th></tr></thead><tbody>{reports.map(report => <Fragment key={report.submission_id}><tr><td><b>{report.candidate_name}</b><small>{report.candidate_email}</small></td><td>{report.question_title ?? "Coding question"}</td><td>{report.execution_results.filter(result => result.passed).length}/{report.execution_results.length} passed</td><td><span className={`status ${report.evaluation_status === "completed" ? "published" : "draft"}`}><i />{report.evaluation_status}</span><small>{report.limitations}</small></td><td className="score">{report.overall_score === null ? "—" : `${report.overall_score.toFixed(1)}/10`}</td></tr><tr><td colSpan={5}><details className="report-details"><summary>Open evaluation report</summary><div className="report-content"><p><b>Reviewer summary:</b> {report.final_summary ?? "No AI summary available."}</p><div className="criterion-grid">{Object.entries(report.criteria ?? {}).map(([criterion, result]) => <div key={criterion}><b>{criterion.replace(/_/g, " ")}</b><strong>{result.score}/10</strong><small>{result.evidence}</small></div>)}</div><div className="report-lists"><div><b>Strengths</b>{(report.strengths ?? []).length ? <ul>{report.strengths?.map(item => <li key={item}>{item}</li>)}</ul> : <p>Not available.</p>}</div><div><b>Weaknesses and suggestions</b>{(report.weaknesses ?? []).length ? <ul>{report.weaknesses?.map(item => <li key={item}>{item}</li>)}</ul> : <p>Not available.</p>}</div></div></div></details></td></tr></Fragment>)}</tbody></table></div>}</section>
  </Shell>;
}

function CandidateHome() {
  const [assessments, setAssessments] = useState<Assessment[]>([]);
  const [attempts, setAttempts] = useState<{ id: string; assessment_id: string; deadline_at: string; completed_at: string | null }[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();
  useEffect(() => {
    void Promise.all([
      api<Assessment[]>("/candidate/assessments"),
      api<{ id: string; assessment_id: string; deadline_at: string; completed_at: string | null }[]>("/candidate/attempts"),
    ]).then(([assigned, candidateAttempts]) => {
      setAssessments(assigned);
      setAttempts(candidateAttempts);
    }).catch(caught => setError(caught instanceof Error ? caught.message : "Could not load assignments.")).finally(() => setLoading(false));
  }, []);
  const start = async (assessment: Assessment) => {
    try { const attempt = await api<Attempt>(`/candidate/assessments/${assessment.id}/attempts`, { method: "POST" }); navigate(`/attempts/${attempt.id}`); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Could not start assessment."); }
  };
  return <Shell user={getUser()}><div className="page-heading candidate-heading"><div><span className="eyebrow">Candidate workspace</span><h1>Your next opportunity starts here.</h1><p>Complete your assigned coding assessments at your own pace within the deadline.</p></div><div className="candidate-badge"><Code2 size={18} /><span>Python assessment</span></div></div>{error && <ErrorMessage>{error}</ErrorMessage>}
    {loading ? <Busy /> : assessments.length === 0 ? <div className="empty-state"><div className="empty-icon"><BriefcaseBusiness /></div><h3>No assessments assigned yet</h3><p>Once an organization invites you and you accept, your assessment appears here.</p></div> : <div className="candidate-assessments">{assessments.map(assessment => {
      const prior = attempts.filter(item => item.assessment_id === assessment.id);
      const active = prior.find(item => !item.completed_at && new Date(item.deadline_at).getTime() > Date.now());
      const expired = prior.some(item => !item.completed_at && new Date(item.deadline_at).getTime() <= Date.now());
      const completed = prior.some(item => item.completed_at);
      const canStart = !assessment.is_archived && !active && assessment.allow_multiple_attempts;
      return <article className="candidate-card" key={assessment.id}><div className="candidate-card-top"><span className="candidate-tag"><Code2 size={14} />Python</span><div className="candidate-card-status">{assessment.is_archived && <span className="status archived"><i />Archived</span>}<span className={`status ${active || (!completed && !expired) || canStart ? "published" : "draft"}`}><i />{active ? "In progress" : completed ? "Completed" : expired ? "Expired" : "Available"}</span></div></div><h2>{assessment.title}</h2><p>{assessment.role}</p><div className="candidate-meta"><span><Clock3 size={15} />{assessment.time_limit_minutes} minutes</span><span><FilePlus2 size={15} />{assessment.questions.length} coding {assessment.questions.length === 1 ? "question" : "questions"}</span></div>{assessment.instructions && <p className="instructions-preview">{assessment.instructions}</p>}
        {active ? <button className="button primary full" onClick={() => navigate(`/attempts/${active.id}`)}>Continue assessment<ArrowRight size={16} /></button>
          : !assessment.is_archived && (canStart || (!prior.length && !expired)) ? <button className="button primary full" onClick={() => void start(assessment)}>{completed ? "Start another attempt" : "Start assessment"}<ArrowRight size={16} /></button>
            : <button className="button secondary full" disabled>{expired ? "Attempt expired" : "Assessment completed"}</button>}
      </article>;
    })}</div>}
  </Shell>;
}

function CodingAttempt() {
  const { id = "" } = useParams();
  const [attempt, setAttempt] = useState<Attempt | null>(null);
  const [questionIndex, setQuestionIndex] = useState(0);
  const [code, setCode] = useState("");
  const [explanation, setExplanation] = useState("");
  const [results, setResults] = useState<{ passed: boolean; status: string; message: string }[] | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [remaining, setRemaining] = useState(0);
  const [finished, setFinished] = useState(false);
  const [submissions, setSubmissions] = useState<SubmissionStatus[]>([]);
  const load = useCallback(async () => {
    try {
      const value = await api<Attempt>(`/candidate/attempts/${id}`);
      setAttempt(value);
      const current = value.assessment.questions[questionIndex];
      setCode(current?.starter_code ?? "");
      setRemaining(Math.max(0, Math.floor((new Date(value.deadline_at).getTime() - new Date(value.server_time).getTime()) / 1000)));
      setSubmissions(value.submissions ?? []);
      if (value.completed_at) setFinished(true);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Could not load assessment."); }
    finally { setLoading(false); }
  }, [id, questionIndex]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (remaining <= 0 || finished) return;
    const timer = window.setInterval(() => setRemaining(value => Math.max(0, value - 1)), 1000);
    return () => window.clearInterval(timer);
  }, [remaining, finished]);
  const question = attempt?.assessment.questions[questionIndex];
  const runSamples = async () => {
    if (!question) return;
    setBusy(true); setError("");
    try { setResults(await api(`/candidate/attempts/${id}/run-samples`, { method: "POST", body: JSON.stringify({ question_id: question.id, code }) })); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Sample run failed."); }
    finally { setBusy(false); }
  };
  const submit = async () => {
    if (!question) return;
    if (!window.confirm("Submit your final solution? You cannot change it afterward.")) return;
    setBusy(true); setError("");
    try {
      const saved = await api<SubmissionStatus>(`/candidate/attempts/${id}/submissions`, { method: "POST", body: JSON.stringify({ question_id: question.id, code, explanation }) });
      setSubmissions(current => [...current.filter(item => item.question_id !== saved.question_id), saved]);
      if (questionIndex + 1 < (attempt?.assessment.questions.length ?? 0)) setQuestionIndex(value => value + 1);
      else setFinished(true);
      setResults(null);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Submission failed."); }
    finally { setBusy(false); }
  };
  const retry = async (submission: SubmissionStatus, operation: "retry-execution" | "retry-evaluation") => {
    setBusy(true); setError("");
    try {
      const updated = await api<SubmissionStatus>(`/candidate/submissions/${submission.id}/${operation}`, { method: "POST" });
      setSubmissions(current => current.map(item => item.id === updated.id ? updated : item));
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Could not retry processing."); }
    finally { setBusy(false); }
  };
  if (loading) return <Shell user={getUser()}><Busy /></Shell>;
  if (finished) return <Shell user={getUser()}><div className="empty-state finish-state"><div className="finish-mark"><Check /></div><span className="eyebrow">Submission received</span><h1>Your work is in.</h1><p>Your code is saved. Execution and evaluation are tracked separately.</p>{error && <ErrorMessage>{error}</ErrorMessage>}  <div className="candidate-processing">{submissions.map(item => <div key={item.id}><span>Question status</span><b>Execution: {item.execution_status.replace(/_/g, " ")}</b><b>Evaluation: {item.evaluation_status.replace(/_/g, " ")}</b>{["sandbox_unavailable", "pending"].includes(item.execution_status) && <button className="button secondary" disabled={busy} onClick={() => void retry(item, "retry-execution")}>Retry execution</button>}{item.execution_status === "completed" && ["failed", "running"].includes(item.evaluation_status) && <button className="button secondary" disabled={busy} onClick={() => void retry(item, "retry-evaluation")}>Retry AI evaluation</button>}</div>)}</div><Link className="button primary" to="/candidate">Return to assessments<ArrowRight size={16} /></Link></div></Shell>;
  if (!attempt || !question) return <Shell user={getUser()}><ErrorMessage>{error || "Assessment question not found."}</ErrorMessage><Link to="/candidate" className="button secondary">Back to assessments</Link></Shell>;
  const formatTime = (value: number) => `${Math.floor(value / 60).toString().padStart(2, "0")}:${(value % 60).toString().padStart(2, "0")}`;
  return <Shell user={getUser()}><div className="attempt-top"><Link to="/candidate" className="back-link">← Exit workspace</Link><div className={`timer ${remaining < 300 ? "timer-warning" : ""}`}><Clock3 size={16} />{formatTime(remaining)}</div></div>
    <div className="attempt-layout"><aside className="problem-pane"><div className="problem-topline"><span className="candidate-tag">Question {questionIndex + 1} of {attempt.assessment.questions.length}</span><span className="status published"><i />Python</span></div><h1>{question.title}</h1><div className="problem-description">{question.prompt.split("\n").map((line, index) => <p key={index}>{line || "\u00a0"}</p>)}</div><div className="problem-rule"><ShieldCheck size={16} /><span>Only your code and sample test results are visible here. Hidden test cases and expected answers are private.</span></div><div className="sample-section"><h3>Sample cases</h3>{question.test_cases.map((test, index) => <div className="sample-case" key={index}><small>Example {index + 1}</small><code>Input: {JSON.stringify(test.input_args)}</code><code>Output: {JSON.stringify(test.expected_output)}</code></div>)}</div><label className="explanation-input">Your approach (optional)<textarea rows={3} value={explanation} onChange={e => setExplanation(e.target.value)} placeholder="Describe your approach and complexity…" /></label></aside>
      <section className="code-pane"><div className="editor-header"><div><Code2 size={16} /><b>Solution.py</b><span>Python 3</span></div><span className="editor-status"><i />Autosave not enabled</span></div><div className="editor-wrap"><Editor height="100%" language="python" theme="vs-dark" value={code} onChange={value => setCode(value ?? "")} options={{ minimap: { enabled: false }, fontSize: 14, lineNumbers: "on", scrollBeyondLastLine: false, automaticLayout: true, tabSize: 4, padding: { top: 18 } }} /></div>
        {error && <ErrorMessage>{error}</ErrorMessage>}
        <div className="results-pane"><div className="results-heading"><div><span className="eyebrow">Test console</span><b>{results ? "Latest sample run" : "Ready to run"}</b></div><span className="muted">Visible sample cases only</span></div>{results ? <div className="test-results">{results.map((result, index) => <div className="test-result" key={index}><span className={result.passed ? "result-check" : "result-fail"}>{result.passed ? <Check size={14} /> : <X size={14} />}</span><b>Example {index + 1}</b><span>{result.passed ? "Passed" : result.status.replace("_", " ")}</span>{result.message && <small>{result.message}</small>}</div>)}</div> : <p className="muted results-empty">Run your solution against visible examples before submitting.</p>}</div>
        <div className="editor-actions"><button className="button secondary" disabled={busy} onClick={() => void runSamples()}><Code2 size={15} />{busy ? "Running…" : "Run sample tests"}</button><button className="button primary" disabled={busy || remaining === 0} onClick={() => void submit()}>{busy ? "Submitting…" : "Submit solution"}<ArrowRight size={15} /></button></div>
      </section>
    </div>
  </Shell>;
}

export default function App() {
  return <Routes>
    <Route path="/robot-test" element={<Suspense fallback={<div className="robot-test-loading-page" />}><RobotTestPage /></Suspense>} />
    <Route path="/login" element={getUser() ? <Navigate to={getUser()?.role === "recruiter" ? "/recruiter" : "/candidate"} replace /> : <AuthPage mode="login" />} />
    <Route path="/register" element={<AuthPage mode="register" />} />
    <Route path="/accept-invitation" element={<AcceptInvitation />} />
    <Route path="/recruiter" element={<Protected role="recruiter"><RecruiterHome /></Protected>} />
    <Route path="/assessments/:id" element={<Protected role="recruiter"><AssessmentDetail /></Protected>} />
    <Route path="/candidate" element={<Protected role="candidate"><CandidateHome /></Protected>} />
    <Route path="/attempts/:id" element={<Protected role="candidate"><CodingAttempt /></Protected>} />
    <Route path="*" element={<Navigate to={getUser()?.role === "candidate" ? "/candidate" : getUser() ? "/recruiter" : "/login"} replace />} />
  </Routes>;
}
