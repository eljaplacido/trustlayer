// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("../../src/api.js", () => ({
  fetchReflections: vi.fn(),
  fetchReflection: vi.fn(),
}));

import {
  fetchReflection,
  fetchReflections,
  type Reflection,
  type ReflectionMeta,
} from "../../src/api.js";
import { ReflectionsPane } from "../../src/ReflectionsPane.js";

const METAS: ReflectionMeta[] = [
  { name: "reflection-2026-05-24.md", date: "2026-05-24" },
  { name: "reflection-2026-05-22.md", date: "2026-05-22" },
];

const FULL: Reflection = {
  name: "reflection-2026-05-24.md",
  date: "2026-05-24",
  content: "# Reflection\nThe researcher hit the external_llm rule twice.",
};

beforeEach(() => {
  vi.mocked(fetchReflections).mockReset();
  vi.mocked(fetchReflection).mockReset();
});
afterEach(() => {
  cleanup();
});

describe("<ReflectionsPane />", () => {
  it("renders the empty-state with the Hermes CLI hint when nothing is in the vault", async () => {
    vi.mocked(fetchReflections).mockResolvedValue([]);
    render(<ReflectionsPane />);
    expect(
      await screen.findByText(/No reflections yet/),
    ).toBeInTheDocument();
    expect(screen.getByText(/hermes\.cli/)).toBeInTheDocument();
  });

  it("lists one button per reflection date", async () => {
    vi.mocked(fetchReflections).mockResolvedValue(METAS);
    render(<ReflectionsPane />);
    expect(await screen.findByRole("button", { name: "2026-05-24" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "2026-05-22" })).toBeInTheDocument();
    // Idle viewer copy until a date is selected.
    expect(screen.getByText(/Select a reflection date/)).toBeInTheDocument();
  });

  it("clicking a date fetches the full reflection and renders its content", async () => {
    vi.mocked(fetchReflections).mockResolvedValue(METAS);
    vi.mocked(fetchReflection).mockResolvedValue(FULL);
    const user = userEvent.setup();

    render(<ReflectionsPane />);
    const button = await screen.findByRole("button", { name: "2026-05-24" });
    await user.click(button);

    await waitFor(() => {
      expect(fetchReflection).toHaveBeenCalledWith(
        "reflection-2026-05-24.md",
      );
    });
    expect(
      await screen.findByText(/external_llm rule twice/),
    ).toBeInTheDocument();
  });

  it("surfaces a reflection fetch error in the viewer", async () => {
    vi.mocked(fetchReflections).mockResolvedValue(METAS);
    vi.mocked(fetchReflection).mockRejectedValue(new Error("HTTP 500"));
    const user = userEvent.setup();

    render(<ReflectionsPane />);
    const button = await screen.findByRole("button", { name: "2026-05-24" });
    await user.click(button);
    expect(await screen.findByText(/HTTP 500/)).toBeInTheDocument();
  });

  it("surfaces a list-side fetch error directly", async () => {
    vi.mocked(fetchReflections).mockRejectedValue(new Error("HTTP 503"));
    render(<ReflectionsPane />);
    await waitFor(() => {
      expect(screen.getByText(/HTTP 503/)).toBeInTheDocument();
    });
  });
});
