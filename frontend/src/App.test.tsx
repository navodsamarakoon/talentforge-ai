import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import App from "./App";
import { Assessment, JobOpening, saveAuth, User } from "./api";

vi.mock("@splinetool/react-spline", () => ({ default: () => null }));

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  vi.unstubAllGlobals();
});

describe("authentication workflow", () => {
  it("signs in a recruiter and routes to the recruiter workspace", async () => {
    const recruiter = {
      id: "user-1",
      email: "recruiter@example.test",
      full_name: "Recruiter",
      role: "recruiter",
      organization_id: "org-1",
    };
    const fetchMock = vi.fn().mockImplementation(async (url: string) => ({
      ok: true,
      status: 200,
      json: async () => url.endsWith("/auth/login")
        ? ({ access_token: "signed-token", user: recruiter })
        : [],
    }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/login"]}><App /></MemoryRouter>);
    await user.type(screen.getByLabelText("Work email"), "recruiter@example.test");
    await user.type(screen.getByLabelText("Password"), "password");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    expect(await screen.findByText("Your first assessment is one step away.")).toBeInTheDocument();
    expect(window.localStorage.getItem("talentforge-token")).toBe("signed-token");
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/auth/login", expect.objectContaining({ method: "POST" }));
  });

  it("keeps login and registration navigation working with the shared robot stage", async () => {
    const user = userEvent.setup();
    const { container } = render(<MemoryRouter initialEntries={["/login"]}><App /></MemoryRouter>);
    expect(container.querySelector(".auth-login-page")).toBeInTheDocument();
    expect(container.querySelector(".auth-cursor-glow")).not.toBeInTheDocument();
    expect(container.querySelector(".auth-robot-stage")).toBeInTheDocument();
    expect(container.querySelector(".auth-card")).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: "Create an account" }));
    expect(screen.getByRole("heading", { name: "Create your workspace" })).toBeInTheDocument();
    expect(container.querySelector(".auth-login-page")).not.toBeInTheDocument();
    expect(container.querySelector(".auth-cursor-glow")).not.toBeInTheDocument();
    expect(container.querySelector(".auth-robot-stage")).toBeInTheDocument();
    expect(screen.getByLabelText("Account type")).toHaveValue("recruiter");
    expect(screen.getByLabelText("Full name")).toBeInTheDocument();
    expect(screen.getByLabelText("Organization")).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Account type"), "candidate");
    expect(screen.queryByLabelText("Organization")).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Account type"), "recruiter");
    expect(screen.getByLabelText("Organization")).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: "Sign in" }));
    expect(screen.getByRole("heading", { name: "Welcome back" })).toBeInTheDocument();
    expect(container.querySelector(".auth-login-page")).toBeInTheDocument();
    expect(container.querySelector(".auth-cursor-glow")).not.toBeInTheDocument();
  });

  it("registers candidates without organization data and routes using the returned role", async () => {
    const candidate = {
      id: "candidate-1",
      email: "candidate@example.com",
      full_name: "Candidate",
      role: "candidate",
      organization_id: null,
    };
    const fetchMock = vi.fn().mockImplementation(async (url: string) => {
      if (url.endsWith("/auth/register/candidate")) {
        return jsonResponse({ access_token: "candidate-token", user: candidate }, 201);
      }
      return jsonResponse([]);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/register"]}><App /></MemoryRouter>);
    await user.selectOptions(screen.getByLabelText("Account type"), "candidate");
    await user.type(screen.getByLabelText("Full name"), "Candidate");
    await user.type(screen.getByLabelText("Email"), "candidate@example.com");
    await user.type(screen.getByLabelText("Password"), "a-strong-candidate-password");
    await user.click(screen.getByRole("button", { name: /create candidate account/i }));

    expect(await screen.findByText("Your next opportunity starts here.")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/auth/register/candidate", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        email: "candidate@example.com",
        password: "a-strong-candidate-password",
        full_name: "Candidate",
      }),
    }));
    expect(window.localStorage.getItem("talentforge-token")).toBe("candidate-token");
  });

  it("keeps recruiter registration on the existing endpoint and includes the organization", async () => {
    const recruiter = {
      id: "recruiter-1",
      email: "recruiter@example.com",
      full_name: "Recruiter",
      role: "recruiter",
      organization_id: "organization-1",
    };
    const fetchMock = vi.fn().mockImplementation(async (url: string) => {
      if (url.endsWith("/auth/register")) {
        return jsonResponse({ access_token: "recruiter-token", user: recruiter }, 201);
      }
      return jsonResponse([]);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/register"]}><App /></MemoryRouter>);
    await user.type(screen.getByLabelText("Full name"), "Recruiter");
    await user.type(screen.getByLabelText("Organization"), "Acme");
    await user.type(screen.getByLabelText("Email"), "recruiter@example.com");
    await user.type(screen.getByLabelText("Password"), "a-strong-recruiter-password");
    await user.click(screen.getByRole("button", { name: /create recruiter account/i }));

    expect(await screen.findByText("Your first assessment is one step away.")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/auth/register", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        email: "recruiter@example.com",
        password: "a-strong-recruiter-password",
        full_name: "Recruiter",
        organization_name: "Acme",
      }),
    }));
    expect(window.localStorage.getItem("talentforge-token")).toBe("recruiter-token");
  });
});

describe("robot test route", () => {
  it("opens directly without authentication", async () => {
    render(<MemoryRouter initialEntries={["/robot-test"]}><App /></MemoryRouter>);

    expect(await screen.findByText(/Viewport:/)).toBeInTheDocument();
    expect(screen.getByText(/Canvas:/)).toBeInTheDocument();
    expect(screen.getByText(/Scene loaded:/)).toHaveTextContent("No");
    expect(screen.queryByRole("heading", { name: "Welcome back" })).not.toBeInTheDocument();
  });
});

const recruiter: User = {
  id: "user-1",
  email: "recruiter@example.test",
  full_name: "Recruiter",
  role: "recruiter",
  organization_id: "org-1",
};

function assessment(overrides: Partial<Assessment> = {}): Assessment {
  return {
    id: "assessment-1",
    title: "Python fundamentals",
    role: "Software Engineer",
    instructions: "Write clear solutions.",
    time_limit_minutes: 45,
    allow_multiple_attempts: false,
    is_published: false,
    is_archived: false,
    has_candidate_records: false,
    created_at: "2026-10-19T12:00:00Z",
    published_at: null,
    questions: [],
    ...overrides,
  };
}

function jobOpening(overrides: Partial<JobOpening> = {}): JobOpening {
  return {
    id: "job-1",
    organization_id: "org-1",
    title: "Software Engineer",
    description: "Build and maintain product features.",
    employment_type: "full-time",
    location: "Remote",
    status: "draft",
    created_at: "2026-10-30T12:00:00Z",
    ...overrides,
  };
}

function renderRecruiter(path = "/recruiter") {
  saveAuth("signed-token", recruiter);
  return render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>);
}

function jsonResponse(body: unknown, status = 200) {
  return { ok: status < 400, status, json: async () => body };
}

describe("recruiter assessment CRUD", () => {
  it("shows loading, empty, and recoverable API-error states", async () => {
    let assessmentLoads = 0;
    const fetchMock = vi.fn().mockImplementation(async (url: string) => {
      if (url.endsWith("/jobs")) return jsonResponse([]);
      assessmentLoads += 1;
      if (assessmentLoads === 2) return jsonResponse({ detail: "Service unavailable." }, 503);
      return jsonResponse([]);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderRecruiter();
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(await screen.findByText("Your first assessment is one step away.")).toBeInTheDocument();

    cleanup();
    renderRecruiter();
    expect(await screen.findByText("Request failed (503): Service unavailable.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Your first assessment is one step away.")).toBeInTheDocument();
  });

  it("creates an assessment only after client validation and confirms success", async () => {
    const created = assessment({ id: "new-assessment", title: "New assessment" });
    const fetchMock = vi.fn().mockImplementation(async (_url: string, options?: RequestInit) => {
      if (options?.method === "POST") return jsonResponse(created, 201);
      return jsonResponse([]);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderRecruiter();
    await user.click(await screen.findByRole("button", { name: /new assessment/i }));
    await user.type(screen.getByLabelText("Assessment title"), "   ");
    await user.click(screen.getByRole("button", { name: /create draft/i }));
    expect(await screen.findByText("Enter an assessment title.")).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([url, options]) => url.endsWith("/assessments") && options?.method === "POST")).toHaveLength(0);

    const title = screen.getByLabelText("Assessment title");
    await user.clear(title);
    await user.type(title, "New assessment");
    await user.click(screen.getByRole("button", { name: /create draft/i }));
    expect(await screen.findByRole("status")).toHaveTextContent('Assessment "New assessment" was created.');
    expect(screen.getByRole("link", { name: /New assessment/ })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/assessments", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        title: "New assessment",
        role: "Software Engineer",
        instructions: "",
        time_limit_minutes: 60,
        allow_multiple_attempts: false,
      }),
    }));
  });

  it("searches and filters fetched assessments", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (url: string) => {
      if (url.endsWith("/jobs")) return jsonResponse([]);
      return jsonResponse([
        assessment(),
        assessment({ id: "published-1", title: "Published algorithms", is_published: true }),
      ]);
    }));
    const user = userEvent.setup();
    const { container } = renderRecruiter();
    expect(await screen.findByText("Python fundamentals")).toBeInTheDocument();
    expect(container.querySelector(".list-arrow")).not.toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Filter by status"), "published");
    expect(screen.getByText("Published algorithms")).toBeInTheDocument();
    expect(screen.queryByText("Python fundamentals")).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Filter by status"), "all");
    await user.type(screen.getByLabelText("Search assessments"), "fundamentals");
    expect(screen.getByText("Python fundamentals")).toBeInTheDocument();
    expect(screen.queryByText("Published algorithms")).not.toBeInTheDocument();
  });

  it("archives assessments with candidate history and restores them from the archived view", async () => {
    const active = assessment({ has_candidate_records: true });
    const archived = assessment({ has_candidate_records: true, is_archived: true });
    const fetchMock = vi.fn().mockImplementation(async (url: string, options?: RequestInit) => {
      if (url.endsWith("/assessments?archived=true") && !options?.method) return jsonResponse([archived]);
      if (url.endsWith("/assessments") && !options?.method) return jsonResponse([active]);
      if (url.endsWith("/archive")) return jsonResponse(archived);
      if (url.endsWith("/unarchive")) return jsonResponse(active);
      return jsonResponse([]);
    });
    vi.stubGlobal("fetch", fetchMock);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();
    renderRecruiter();

    expect(await screen.findByRole("button", { name: "Archive" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Archive" }));
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining("invitations, attempts, submissions, and reports are preserved"));
    expect(await screen.findByRole("status")).toHaveTextContent("Candidate history is preserved.");
    expect(screen.queryByText("Python fundamentals")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Archived" }));
    expect(await screen.findByText("Python fundamentals")).toBeInTheDocument();
    expect(screen.getAllByText("Archived")).toHaveLength(2);
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/assessments?archived=true", expect.anything());
    await user.click(screen.getByRole("button", { name: "Restore" }));
    expect(await screen.findByRole("status")).toHaveTextContent("restored to the active workspace");
    expect(screen.queryByText("Python fundamentals")).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/assessments/assessment-1/unarchive", expect.objectContaining({ method: "POST" }));
  });

  it("keeps an assessment visible and reports server errors when archiving fails", async () => {
    const fetchMock = vi.fn().mockImplementation(async (url: string, options?: RequestInit) =>
      url.endsWith("/jobs")
        ? jsonResponse([])
        : options?.method === "POST"
          ? jsonResponse({ detail: "Assessment is already archived." }, 409)
          : jsonResponse([assessment({ has_candidate_records: true })]));
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();
    renderRecruiter();

    await user.click(await screen.findByRole("button", { name: "Archive" }));
    expect(await screen.findByText("Request failed (409): Assessment is already archived.")).toBeInTheDocument();
    expect(screen.getByText("Python fundamentals")).toBeInTheDocument();
  });

  it("keeps assessment details navigable from the card without Edit or chevron actions", async () => {
    let saved = assessment();
    const fetchMock = vi.fn().mockImplementation(async (url: string, options?: RequestInit) => {
      if (url.endsWith("/jobs")) return jsonResponse([]);
      if (url.endsWith("/assessments") && !options?.method) return jsonResponse([saved]);
      if (url.endsWith("/compare")) return jsonResponse([]);
      if (options?.method === "PATCH") {
        const body = JSON.parse(String(options.body)) as Partial<Assessment>;
        saved = assessment({
          ...saved,
          title: body.title,
          role: body.role,
          instructions: body.instructions,
          time_limit_minutes: body.time_limit_minutes,
          allow_multiple_attempts: body.allow_multiple_attempts,
        });
        return jsonResponse(saved);
      }
      return jsonResponse(saved);
    });
    vi.stubGlobal("fetch", fetchMock);
    const { container } = renderRecruiter();
    expect(await screen.findByRole("link", { name: /Python fundamentals/ })).toHaveAttribute("href", "/assessments/assessment-1");
    expect(screen.queryByRole("link", { name: "Edit" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "View" })).not.toBeInTheDocument();
    expect(container.querySelector(".list-arrow")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
  });

  it("updates assessment details through the existing PATCH endpoint", async () => {
    let saved = assessment();
    const fetchMock = vi.fn().mockImplementation(async (url: string, options?: RequestInit) => {
      if (url.endsWith("/compare")) return jsonResponse([]);
      if (options?.method === "PATCH") {
        const body = JSON.parse(String(options.body)) as Partial<Assessment>;
        saved = assessment({
          ...saved,
          title: body.title,
          role: body.role,
          instructions: body.instructions,
          time_limit_minutes: body.time_limit_minutes,
          allow_multiple_attempts: body.allow_multiple_attempts,
        });
        return jsonResponse(saved);
      }
      return jsonResponse(saved);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderRecruiter("/assessments/assessment-1");
    await user.clear(await screen.findByLabelText("Title"));
    await user.type(screen.getByLabelText("Title"), "Updated title");
    await user.selectOptions(screen.getByLabelText("Role"), "Software Engineering Intern");
    await user.clear(screen.getByLabelText("Time limit in minutes"));
    await user.type(screen.getByLabelText("Time limit in minutes"), "90");
    await user.clear(screen.getByLabelText("Instructions"));
    await user.type(screen.getByLabelText("Instructions"), "Updated instructions.");
    await user.click(screen.getByRole("button", { name: "Save assessment details" }));
    expect(await screen.findByRole("heading", { name: "Updated title" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/assessments/assessment-1", expect.objectContaining({
      method: "PATCH",
      body: JSON.stringify({
        title: "Updated title",
        role: "Software Engineering Intern",
        instructions: "Updated instructions.",
        time_limit_minutes: 90,
        allow_multiple_attempts: false,
      }),
    }));
  });

  it("opens a question from its row, loads its values, saves through its question endpoint", async () => {
    const existingQuestion = {
      id: "question-1",
      position: 0,
      title: "Add Two Numbers",
      prompt: "Return the sum of two values.",
      function_name: "add",
      starter_code: "def add(a, b):\n    pass\n",
      test_cases: [
        { input_args: [1, 2], expected_output: 3, is_hidden: false },
        { input_args: [5, 6], expected_output: 11, is_hidden: true },
      ],
    };
    let savedAssessment = assessment({ questions: [existingQuestion] });
    const fetchMock = vi.fn().mockImplementation(async (url: string, options?: RequestInit) => {
      if (url.endsWith("/compare")) return jsonResponse([]);
      if (options?.method === "PATCH" && url.endsWith("/questions/question-1")) {
        const payload = JSON.parse(String(options.body)) as Omit<typeof existingQuestion, "id">;
        savedAssessment = assessment({
          ...savedAssessment,
          questions: [{ ...payload, id: "question-1" }],
        });
        return jsonResponse(savedAssessment);
      }
      return jsonResponse(savedAssessment);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderRecruiter("/assessments/assessment-1");

    await user.click(await screen.findByRole("button", { name: "Edit question Add Two Numbers" }));
    expect(screen.getByLabelText("Question title")).toHaveValue("Add Two Numbers");
    expect(screen.getByLabelText("Function name")).toHaveValue("add");
    expect(screen.getByLabelText("Question order")).toHaveValue(0);
    expect(screen.getByLabelText("Problem statement")).toHaveValue("Return the sum of two values.");
    expect(screen.getByLabelText("Python starter code")).toHaveValue("def add(a, b):\n    pass\n");
    const testCaseField = screen.getByLabelText(/Test cases \(JSON\)/) as HTMLTextAreaElement;
    expect(JSON.parse(testCaseField.value)).toEqual(existingQuestion.test_cases);

    await user.clear(screen.getByLabelText("Question title"));
    await user.type(screen.getByLabelText("Question title"), "Add integers");
    await user.clear(screen.getByLabelText("Function name"));
    await user.type(screen.getByLabelText("Function name"), "sum_values");
    await user.clear(screen.getByLabelText("Question order"));
    await user.type(screen.getByLabelText("Question order"), "2");
    await user.clear(screen.getByLabelText("Problem statement"));
    await user.type(screen.getByLabelText("Problem statement"), "Sum two integers.");
    await user.clear(screen.getByLabelText("Python starter code"));
    await user.type(screen.getByLabelText("Python starter code"), "def sum_values(a, b):\n    return a + b\n");
    const cases = [
      { input_args: [3, 4], expected_output: 7, is_hidden: false },
      { input_args: [8, 9], expected_output: 17, is_hidden: true },
    ];
    fireEvent.change(testCaseField, { target: { value: JSON.stringify(cases) } });
    await user.click(screen.getByRole("button", { name: "Save question changes" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Question changes saved.");
    expect(await screen.findByRole("button", { name: "Edit question Add integers" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/assessments/assessment-1/questions/question-1", expect.objectContaining({
      method: "PATCH",
      body: JSON.stringify({
        position: 2,
        title: "Add integers",
        prompt: "Sum two integers.",
        function_name: "sum_values",
        starter_code: "def sum_values(a, b):\n    return a + b\n",
        test_cases: cases,
      }),
    }));
    expect(savedAssessment.questions[0].test_cases.map(testCase => testCase.is_hidden)).toEqual([false, true]);
  });

  it("cancels question editing without sending an update", async () => {
    const originalQuestion = {
      id: "question-1",
      position: 0,
      title: "Add Two Numbers",
      prompt: "Return the sum of two values.",
      function_name: "add",
      starter_code: "def add(a, b):\n    pass\n",
      test_cases: [
        { input_args: [1, 2], expected_output: 3, is_hidden: false },
        { input_args: [5, 6], expected_output: 11, is_hidden: true },
      ],
    };
    const fetchMock = vi.fn().mockImplementation(async (url: string) =>
      url.endsWith("/compare") ? jsonResponse([]) : jsonResponse(assessment({ questions: [originalQuestion] })));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderRecruiter("/assessments/assessment-1");

    await user.click(await screen.findByRole("button", { name: "Edit question Add Two Numbers" }));
    await user.clear(screen.getByLabelText("Question title"));
    await user.type(screen.getByLabelText("Question title"), "Unsaved title");
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.getByRole("heading", { name: "Add a Python coding question" })).toBeInTheDocument();
    expect(screen.getByLabelText("Question title")).toHaveValue("");
    expect(screen.getByRole("button", { name: "Edit question Add Two Numbers" })).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalledWith(
      "http://localhost:8000/api/assessments/assessment-1/questions/question-1",
      expect.objectContaining({ method: "PATCH" }),
    );
  });

  it("adds a new question through POST without updating an existing question", async () => {
    let savedAssessment = assessment();
    const fetchMock = vi.fn().mockImplementation(async (url: string, options?: RequestInit) => {
      if (url.endsWith("/compare")) return jsonResponse([]);
      if (options?.method === "POST" && url.endsWith("/questions")) {
        const payload = JSON.parse(String(options.body)) as Omit<Assessment["questions"][number], "id">;
        savedAssessment = assessment({
          ...savedAssessment,
          questions: [{ ...payload, id: "new-question" }],
        });
        return jsonResponse(savedAssessment, 201);
      }
      return jsonResponse(savedAssessment);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderRecruiter("/assessments/assessment-1");
    await screen.findByRole("heading", { name: "Add a Python coding question" });
    await user.type(screen.getByLabelText("Question title"), "Multiply values");
    await user.clear(screen.getByLabelText("Function name"));
    await user.type(screen.getByLabelText("Function name"), "multiply");
    await user.type(screen.getByLabelText("Problem statement"), "Return the product.");

    await user.click(screen.getByRole("button", { name: "Add question" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Question added.");
    expect(await screen.findByRole("button", { name: "Edit question Multiply values" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/assessments/assessment-1/questions", expect.objectContaining({
      method: "POST",
    }));
    expect(fetchMock.mock.calls.filter(([, options]) => options?.method === "PATCH")).toHaveLength(0);
  });

  it("confirms deletion, removes only on success, and preserves the row on failure", async () => {
    let failDelete = true;
    const fetchMock = vi.fn().mockImplementation(async (url: string, options?: RequestInit) =>
      url.endsWith("/jobs")
        ? jsonResponse([])
        : options?.method === "DELETE"
          ? failDelete ? jsonResponse({ detail: "Assessment has candidate records." }, 409) : { ok: true, status: 204 }
          : jsonResponse([assessment()]));
    vi.stubGlobal("fetch", fetchMock);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();
    renderRecruiter();
    expect(await screen.findByText("Python fundamentals")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining("Delete \"Python fundamentals\"?"));
    expect(await screen.findByText("Request failed (409): Assessment has candidate records.")).toBeInTheDocument();
    expect(screen.getByText("Python fundamentals")).toBeInTheDocument();

    failDelete = false;
    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(await screen.findByRole("status")).toHaveTextContent('Assessment "Python fundamentals" was deleted.');
    expect(screen.queryByText("Python fundamentals")).not.toBeInTheDocument();
  });
});

describe("recruiter job vacancy management", () => {
  it("displays real job vacancies and creates new openings as drafts", async () => {
    let vacancies = [jobOpening({ title: "Existing Engineer", status: "published" })];
    const fetchMock = vi.fn().mockImplementation(async (url: string, options?: RequestInit) => {
      if (url.endsWith("/jobs") && options?.method === "POST") {
        const body = JSON.parse(String(options.body)) as Omit<JobOpening, "id" | "organization_id" | "status" | "created_at">;
        const created = jobOpening({ ...body, id: "job-new", status: "draft", created_at: "2026-10-31T12:00:00Z" });
        vacancies = [created, ...vacancies];
        return jsonResponse(created, 201);
      }
      if (url.endsWith("/jobs")) return jsonResponse(vacancies);
      return jsonResponse([]);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderRecruiter();

    expect(await screen.findByText("Existing Engineer")).toBeInTheDocument();
    expect(screen.getByText(/Full-time/)).toBeInTheDocument();
    expect(screen.getByText(/Remote.*Created/)).toBeInTheDocument();
    expect(screen.getByText("published", { selector: ".status" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /create job vacancy/i }));
    await user.type(screen.getByLabelText("Job Title"), "Software Engineering Intern");
    await user.selectOptions(screen.getByLabelText("Employment Type"), "internship");
    await user.type(screen.getByLabelText("Location"), "Colombo");
    await user.type(screen.getByLabelText("Job Description"), "Work with the engineering team.");
    await user.click(screen.getAllByRole("button", { name: /create job vacancy/i })[1]);

    expect(await screen.findByText("Software Engineering Intern")).toBeInTheDocument();
    expect(screen.getByText("draft", { selector: ".status" })).toBeInTheDocument();
    expect(await screen.findByRole("status")).toHaveTextContent('Job vacancy "Software Engineering Intern" was created as a draft.');
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/jobs", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        title: "Software Engineering Intern",
        description: "Work with the engineering team.",
        employment_type: "internship",
        location: "Colombo",
      }),
    }));
  });

  it("publishes draft vacancies and closes published vacancies, refreshing the list", async () => {
    let vacancy = jobOpening();
    const fetchMock = vi.fn().mockImplementation(async (url: string, options?: RequestInit) => {
      if (url.endsWith("/jobs") && !options?.method) return jsonResponse([vacancy]);
      if (url.endsWith("/publish")) {
        vacancy = jobOpening({ ...vacancy, status: "published" });
        return jsonResponse(vacancy);
      }
      if (url.endsWith("/close")) {
        vacancy = jobOpening({ ...vacancy, status: "closed" });
        return jsonResponse(vacancy);
      }
      return jsonResponse([]);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderRecruiter();

    expect(await screen.findByText("Software Engineer")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Publish Job" }));
    expect(await screen.findByRole("button", { name: "Close Job" })).toBeInTheDocument();
    expect(await screen.findByRole("status")).toHaveTextContent('Job vacancy "Software Engineer" was published.');
    expect(screen.getByText("published", { selector: ".status" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Close Job" }));
    expect(await screen.findByText("closed", { selector: ".status" })).toBeInTheDocument();
    expect(await screen.findByRole("status")).toHaveTextContent('Job vacancy "Software Engineer" was closed.');
    expect(screen.queryByRole("button", { name: "Publish Job" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Close Job" })).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/jobs/job-1/publish", expect.objectContaining({ method: "POST" }));
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/jobs/job-1/close", expect.objectContaining({ method: "POST" }));
    expect(fetchMock.mock.calls.filter(([url, options]) => url.endsWith("/jobs") && !options?.method)).toHaveLength(3);
  });

  it("shows vacancies API errors and validates creation input", async () => {
    const fetchMock = vi.fn().mockImplementation(async (url: string, options?: RequestInit) => {
      if (url.endsWith("/jobs") && options?.method === "POST") {
        return jsonResponse({ detail: "Job description is invalid." }, 422);
      }
      if (url.endsWith("/jobs")) return jsonResponse([]);
      return jsonResponse([]);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderRecruiter();
    await user.click(await screen.findByRole("button", { name: /create job vacancy/i }));
    await user.type(screen.getByLabelText("Job Title"), "   ");
    await user.type(screen.getByLabelText("Job Description"), "Description");
    await user.type(screen.getByLabelText("Location"), "Remote");
    await user.click(screen.getAllByRole("button", { name: /create job vacancy/i })[1]);

    expect(await screen.findByText("Enter a job title, description, and location.")).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([url, options]) => url.endsWith("/jobs") && options?.method === "POST")).toHaveLength(0);

    await user.clear(screen.getByLabelText("Job Title"));
    await user.type(screen.getByLabelText("Job Title"), "Software Engineer");
    await user.click(screen.getAllByRole("button", { name: /create job vacancy/i })[1]);
    expect(await screen.findByText("Request failed (422): Job description is invalid.")).toBeInTheDocument();
  });
});

describe("candidate access to archived assessments", () => {
  it("keeps an in-progress archived assessment resumable without offering a new start", async () => {
    const candidate: User = {
      id: "candidate-1",
      email: "candidate@example.test",
      full_name: "Candidate",
      role: "candidate",
      organization_id: null,
    };
    saveAuth("candidate-token", candidate);
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (url: string) => {
      if (url.endsWith("/candidate/assessments")) {
        return jsonResponse([assessment({ is_published: true, is_archived: true, allow_multiple_attempts: true })]);
      }
      if (url.endsWith("/candidate/attempts")) {
        return jsonResponse([{
          id: "attempt-in-progress",
          assessment_id: "assessment-1",
          deadline_at: new Date(Date.now() + 60_000).toISOString(),
          completed_at: null,
        }]);
      }
      return jsonResponse([]);
    }));
    render(<MemoryRouter initialEntries={["/candidate"]}><App /></MemoryRouter>);

    expect(await screen.findByText("Python fundamentals")).toBeInTheDocument();
    expect(screen.getByText("Archived")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /continue assessment/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /start assessment/i })).not.toBeInTheDocument();
  });
});

describe("candidate job vacancies", () => {
  const candidate: User = {
    id: "candidate-jobs-1",
    email: "candidate@example.test",
    full_name: "Candidate",
    role: "candidate",
    organization_id: null,
  };

  it("renders published vacancies with enabled Apply Now buttons", async () => {
    saveAuth("candidate-token", candidate);
    const vacancies = [
      jobOpening({
        id: "published-internship",
        title: "Software Engineering Intern",
        employment_type: "internship",
        location: "Colombo",
        description: "Help build reliable software for our customers.",
        status: "published",
      }),
      jobOpening({
        id: "published-engineer",
        title: "Software Engineer",
        employment_type: "full-time",
        location: "Remote",
        description: "Own product features from design through delivery.",
        status: "published",
      }),
      jobOpening({ id: "draft-job", title: "Hidden draft", status: "draft" }),
      jobOpening({ id: "closed-job", title: "Hidden closed role", status: "closed" }),
    ];
    const fetchMock = vi.fn().mockImplementation(async (url: string) => {
      if (url.endsWith("/candidate/jobs")) return jsonResponse(vacancies);
      return jsonResponse([]);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/candidate"]}><App /></MemoryRouter>);

    expect(await screen.findByRole("heading", { name: /Available Job Vacancies/ })).toBeInTheDocument();
    expect(await screen.findByText("Software Engineering Intern")).toBeInTheDocument();
    expect(screen.getByText("Software Engineer")).toBeInTheDocument();
    expect(screen.getByText(/Internship.*Colombo/)).toBeInTheDocument();
    expect(screen.getByText("Help build reliable software for our customers.")).toBeInTheDocument();
    expect(screen.getByText("Own product features from design through delivery.")).toBeInTheDocument();
    expect(screen.getAllByText("Open", { selector: ".status" })).toHaveLength(2);
    expect(screen.queryByText("Hidden draft")).not.toBeInTheDocument();
    expect(screen.queryByText("Hidden closed role")).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/candidate/jobs", expect.objectContaining({
      headers: expect.objectContaining({ Authorization: "Bearer candidate-token" }),
    }));

    const applyButtons = screen.getAllByRole("button", { name: "Apply Now" });
    expect(applyButtons).toHaveLength(2);
    expect(applyButtons[0]).toBeEnabled();
    expect(screen.queryByText("Coming Soon")).not.toBeInTheDocument();
    await user.click(applyButtons[0]);
    expect(screen.getByRole("dialog", { name: "Software Engineering Intern" })).toBeInTheDocument();
    expect(screen.getByLabelText("CV file")).toHaveAttribute("accept", ".pdf,.docx");
  });

  it.each([
    ["PDF", "resume.pdf", "application/pdf"],
    ["DOCX", "resume.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"],
  ])("accepts a selected %s CV and submits it using authenticated multipart form data", async (_format, filename, mimeType) => {
    saveAuth("candidate-token", candidate);
    const fetchMock = vi.fn().mockImplementation(async (url: string) => {
      if (url.endsWith("/candidate/jobs")) return jsonResponse([jobOpening({ status: "published" })]);
      if (url.endsWith("/candidate/applications")) {
        return jsonResponse(fetchMock.mock.calls.some(([requestedUrl]) => String(requestedUrl).includes("/applications") && String(requestedUrl).includes("/jobs/"))
          ? [{ id: "application-1", job_opening_id: "job-1", job_title: "Software Engineer", original_cv_filename: filename, status: "submitted", submitted_at: "2026-10-30T12:00:00Z" }]
          : []);
      }
      if (String(url).includes("/candidate/jobs/") && String(url).endsWith("/applications")) {
        return jsonResponse({ id: "application-1", job_opening_id: "job-1", status: "submitted", submitted_at: "2026-10-30T12:00:00Z", original_cv_filename: filename }, 201);
      }
      return jsonResponse([]);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/candidate"]}><App /></MemoryRouter>);
    await user.click(await screen.findByRole("button", { name: "Apply Now" }));
    const file = new File(["sample CV"], filename, { type: mimeType });
    fireEvent.change(screen.getByLabelText("CV file"), { target: { files: [file] } });
    expect(screen.getByText(`Selected: ${filename}`)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Submit Application" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Application submitted for Software Engineer.");
    const appliedJobCard = screen.getAllByRole("article").find(article => article.classList.contains("candidate-job-card"));
    expect(appliedJobCard && within(appliedJobCard).getByRole("button", { name: "Applied" })).toBeDisabled();
    const uploadCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/candidate/jobs/job-1/applications"));
    expect(uploadCall).toBeDefined();
    expect(uploadCall?.[1]).toEqual(expect.objectContaining({
      method: "POST",
      body: expect.any(FormData),
      headers: expect.objectContaining({ Authorization: "Bearer candidate-token" }),
    }));
    expect((uploadCall?.[1] as RequestInit).headers).not.toHaveProperty("Content-Type");
    expect(((uploadCall?.[1] as RequestInit).body as FormData).get("cv")).toBe(file);
    expect(await screen.findByRole("heading", { name: "My Job Applications" })).toBeInTheDocument();
    expect(screen.getByText((_, element) => element?.tagName === "P" && element.textContent?.includes(filename) === true)).toBeInTheDocument();
  });

  it.each([
    ["PNG", "resume.png", "image/png", "Choose a PDF or DOCX file."],
    ["JPG", "resume.jpg", "image/jpeg", "Choose a PDF or DOCX file."],
    ["oversized", "large.pdf", "application/pdf", "The selected CV must be 10 MB or smaller."],
    ["empty", "empty.pdf", "application/pdf", "The selected CV is empty. Choose a non-empty PDF or DOCX file."],
  ])("rejects %s files before submission", async (_label, filename, mimeType, expectedMessage) => {
    saveAuth("candidate-token", candidate);
    const fetchMock = vi.fn().mockImplementation(async (url: string) => {
      if (url.endsWith("/candidate/jobs")) return jsonResponse([jobOpening({ status: "published" })]);
      return jsonResponse([]);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/candidate"]}><App /></MemoryRouter>);
    await user.click(await screen.findByRole("button", { name: "Apply Now" }));
    const contents = filename === "large.pdf" ? new Uint8Array(10 * 1024 * 1024 + 1) : filename === "empty.pdf" ? "" : "invalid CV";
    fireEvent.change(screen.getByLabelText("CV file"), { target: { files: [new File([contents], filename, { type: mimeType })] } });

    expect(await screen.findByRole("alert")).toHaveTextContent(expectedMessage);
    expect(screen.getByRole("button", { name: "Submit Application" })).toBeDisabled();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/candidate/jobs/") && String(url).endsWith("/applications"))).toBe(false);
  });

  it("shows loading application history and handles a duplicate application response", async () => {
    saveAuth("candidate-token", candidate);
    let finishHistory!: (response: ReturnType<typeof jsonResponse>) => void;
    const pendingHistory = new Promise<ReturnType<typeof jsonResponse>>(resolve => { finishHistory = resolve; });
    const fetchMock = vi.fn().mockImplementation(async (url: string) => {
      if (url.endsWith("/candidate/jobs")) return jsonResponse([jobOpening({ status: "published" })]);
      if (url.endsWith("/candidate/applications")) return pendingHistory;
      if (String(url).includes("/candidate/jobs/") && String(url).endsWith("/applications")) {
        return jsonResponse({ detail: "Duplicate application." }, 409);
      }
      return jsonResponse([]);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/candidate"]}><App /></MemoryRouter>);
    expect(await screen.findByText("Loading your job applications…")).toBeInTheDocument();
    finishHistory(jsonResponse([]));
    await user.click(await screen.findByRole("button", { name: "Apply Now" }));
    fireEvent.change(screen.getByLabelText("CV file"), { target: { files: [new File(["cv"], "resume.pdf", { type: "application/pdf" })] } });
    await user.click(screen.getByRole("button", { name: "Submit Application" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("You have already applied for this job, or it is no longer accepting applications.");
    expect(screen.getByRole("button", { name: "Apply Now" })).toBeEnabled();
  });

  it("disables repeat submission while an application upload is in progress", async () => {
    saveAuth("candidate-token", candidate);
    let finishUpload!: (response: ReturnType<typeof jsonResponse>) => void;
    const pendingUpload = new Promise<ReturnType<typeof jsonResponse>>(resolve => { finishUpload = resolve; });
    const fetchMock = vi.fn().mockImplementation(async (url: string) => {
      if (url.endsWith("/candidate/jobs")) return jsonResponse([jobOpening({ status: "published" })]);
      if (String(url).includes("/candidate/jobs/") && String(url).endsWith("/applications")) return pendingUpload;
      if (url.endsWith("/candidate/applications")) {
        return jsonResponse(fetchMock.mock.calls.some(([requestedUrl]) => String(requestedUrl).includes("/candidate/jobs/") && String(requestedUrl).endsWith("/applications"))
          ? [{ id: "application-1", job_opening_id: "job-1", job_title: "Software Engineer", original_cv_filename: "resume.pdf", status: "submitted", submitted_at: "2026-10-30T12:00:00Z" }]
          : []);
      }
      return jsonResponse([]);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/candidate"]}><App /></MemoryRouter>);
    await user.click(await screen.findByRole("button", { name: "Apply Now" }));
    fireEvent.change(screen.getByLabelText("CV file"), { target: { files: [new File(["cv"], "resume.pdf", { type: "application/pdf" })] } });
    await user.click(screen.getByRole("button", { name: "Submit Application" }));

    expect(screen.getByRole("button", { name: "Submitting…" })).toBeDisabled();
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/candidate/jobs/job-1/applications"))).toHaveLength(1);
    finishUpload(jsonResponse({ id: "application-1", job_opening_id: "job-1", status: "submitted", submitted_at: "2026-10-30T12:00:00Z", original_cv_filename: "resume.pdf" }, 201));
    expect(await screen.findByRole("button", { name: "Applied" })).toBeDisabled();
  });

  it("shows actual application history with status and submission date", async () => {
    saveAuth("candidate-token", candidate);
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (url: string) => {
      if (url.endsWith("/candidate/jobs")) return jsonResponse([jobOpening({
        id: "job-1",
        title: "Software Engineering Intern",
        status: "published",
      })]);
      if (url.endsWith("/candidate/applications")) {
        return jsonResponse([{
          id: "application-1",
          job_opening_id: "job-1",
          job_title: "Software Engineering Intern",
          original_cv_filename: "candidate-cv.pdf",
          status: "screening",
          submitted_at: "2026-10-30T12:00:00Z",
        }]);
      }
      return jsonResponse([]);
    }));
    render(<MemoryRouter initialEntries={["/candidate"]}><App /></MemoryRouter>);

    expect(await screen.findAllByText("Software Engineering Intern")).toHaveLength(2);
    expect(screen.getByText("CV: candidate-cv.pdf")).toBeInTheDocument();
    expect(screen.getByText("Screening")).toBeInTheDocument();
    expect(screen.getByText(/Submitted/)).toBeInTheDocument();
    const appliedJobCard = screen.getAllByRole("article").find(article => article.classList.contains("candidate-job-card"));
    expect(appliedJobCard && within(appliedJobCard).getByRole("button", { name: "Applied" })).toBeDisabled();
  });

  it("uses job opening IDs for duplicate-title jobs and restores Applied from history", async () => {
    saveAuth("candidate-token", candidate);
    const repeatedTitleJobs = [
      jobOpening({ id: "job-applied", title: "Software Engineer", status: "published" }),
      jobOpening({ id: "job-not-applied", title: "Software Engineer", status: "published" }),
    ];
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (url: string) => {
      if (url.endsWith("/candidate/jobs")) return jsonResponse(repeatedTitleJobs);
      if (url.endsWith("/candidate/applications")) {
        return jsonResponse([{
          id: "application-1",
          job_opening_id: "job-applied",
          job_title: "Software Engineer",
          original_cv_filename: "resume.pdf",
          status: "submitted",
          submitted_at: "2026-10-30T12:00:00Z",
        }]);
      }
      return jsonResponse([]);
    }));
    render(<MemoryRouter initialEntries={["/candidate"]}><App /></MemoryRouter>);

    await screen.findByText("CV: resume.pdf");
    const cards = screen.getAllByRole("article").filter(article => article.classList.contains("candidate-job-card"));
    expect(cards).toHaveLength(2);
    expect(within(cards[0]).getByRole("button", { name: "Applied" })).toBeDisabled();
    expect(within(cards[1]).getByRole("button", { name: "Apply Now" })).toBeEnabled();
  });

  it("shows empty and error states for candidate application history", async () => {
    saveAuth("candidate-token", candidate);
    let historyLoads = 0;
    const fetchMock = vi.fn().mockImplementation(async (url: string) => {
      if (url.endsWith("/candidate/applications")) {
        historyLoads += 1;
        return historyLoads === 1 ? jsonResponse({ detail: "private server detail" }, 503) : jsonResponse([]);
      }
      return jsonResponse([]);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/candidate"]}><App /></MemoryRouter>);

    expect(await screen.findByText("Could not load your job applications. Please try again.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("No job applications yet.")).toBeInTheDocument();
  });

  it("shows a loading state then an empty state when no vacancies are published", async () => {
    saveAuth("candidate-token", candidate);
    let finishJobs!: (response: ReturnType<typeof jsonResponse>) => void;
    const pendingJobs = new Promise<ReturnType<typeof jsonResponse>>(resolve => { finishJobs = resolve; });
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (url: string) => {
      if (url.endsWith("/candidate/jobs")) return pendingJobs;
      return jsonResponse([]);
    }));
    render(<MemoryRouter initialEntries={["/candidate"]}><App /></MemoryRouter>);

    expect(await screen.findByText("Loading job vacancies…")).toBeInTheDocument();
    finishJobs(jsonResponse([]));
    expect(await screen.findByText("No open job vacancies yet.")).toBeInTheDocument();
  });

  it("shows job API errors with retry while keeping assigned coding assessments available", async () => {
    saveAuth("candidate-token", candidate);
    let jobRequestCount = 0;
    const assigned = assessment({ is_published: true, title: "Invited coding assessment" });
    const fetchMock = vi.fn().mockImplementation(async (url: string) => {
      if (url.endsWith("/candidate/jobs")) {
        jobRequestCount += 1;
        if (jobRequestCount === 1) return jsonResponse({ detail: "Job service unavailable." }, 503);
        return jsonResponse([jobOpening({ status: "published" })]);
      }
      if (url.endsWith("/candidate/assessments")) return jsonResponse([assigned]);
      return jsonResponse([]);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/candidate"]}><App /></MemoryRouter>);

    expect(await screen.findByText("Request failed (503): Job service unavailable.")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Invited coding assessment" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start assessment" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: "Software Engineer" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start assessment" })).toBeInTheDocument();
  });
});
