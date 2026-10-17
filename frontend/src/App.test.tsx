import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import App from "./App";

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
});
