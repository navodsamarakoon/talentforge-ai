import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import App from "./App";
import { Assessment, saveAuth, User } from "./api";

vi.mock("@splinetool/react-spline", () => ({
  default: ({ scene }: { scene: string }) => <div data-testid="spline-scene" data-scene={scene} />,
}));

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
    const { container } = render(<MemoryRouter initialEntries={["/login"]}><App /></MemoryRouter>);
    expect(container.querySelector(".auth-cursor-glow")).not.toBeInTheDocument();
    expect(await screen.findByTestId("spline-scene")).toHaveAttribute("data-scene", "https://prod.spline.design/0F4Z9rX1AsFWaYh7/scene.splinecode");
    await user.type(screen.getByLabelText("Work email"), "recruiter@example.test");
    await user.type(screen.getByLabelText("Password"), "password");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    expect(await screen.findByText("Your first assessment is one step away.")).toBeInTheDocument();
    expect(container.querySelector(".auth-cursor-glow")).not.toBeInTheDocument();
    expect(window.localStorage.getItem("talentforge-token")).toBe("signed-token");
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/auth/login", expect.objectContaining({ method: "POST" }));
  });

  it("keeps the redesigned auth composition on both login and registration", async () => {
    const user = userEvent.setup();
    const { container } = render(<MemoryRouter initialEntries={["/login"]}><App /></MemoryRouter>);
    expect(container.querySelector(".auth-cursor-glow")).not.toBeInTheDocument();
    expect(container.querySelector(".robot-stage")).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: "Create an account" }));
    expect(screen.getByRole("heading", { name: "Create your workspace" })).toBeInTheDocument();
    expect(container.querySelector(".auth-cursor-glow")).not.toBeInTheDocument();
    expect(container.querySelector(".robot-stage")).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: "Sign in" }));
    expect(screen.getByRole("heading", { name: "Welcome back" })).toBeInTheDocument();
    expect(container.querySelector(".auth-cursor-glow")).not.toBeInTheDocument();
  });

  it("skips loading the Spline runtime on small screens while keeping auth controls available", () => {
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: query === "(max-width: 600px)",
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));
    const { container } = render(<MemoryRouter initialEntries={["/login"]}><App /></MemoryRouter>);

    expect(container.querySelector(".spline-viewport")).not.toBeInTheDocument();
    expect(screen.getByText("3D preview available on larger screens")).toBeInTheDocument();
    expect(screen.getByLabelText("Work email")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign in/i })).toBeInTheDocument();
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

function renderRecruiter(path = "/recruiter") {
  saveAuth("signed-token", recruiter);
  return render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>);
}

function jsonResponse(body: unknown, status = 200) {
  return { ok: status < 400, status, json: async () => body };
}

describe("recruiter assessment CRUD", () => {
  it("shows loading, empty, and recoverable API-error states", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({ detail: "Service unavailable." }) })
      .mockResolvedValueOnce(jsonResponse([]));
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
    expect(fetchMock).toHaveBeenCalledTimes(1);

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
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse([
      assessment(),
      assessment({ id: "published-1", title: "Published algorithms", is_published: true }),
    ])));
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
    const fetchMock = vi.fn().mockImplementation(async (_url: string, options?: RequestInit) =>
      options?.method === "POST"
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
    const fetchMock = vi.fn().mockImplementation(async (_url: string, options?: RequestInit) =>
      options?.method === "DELETE"
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
