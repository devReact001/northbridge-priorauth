import { NextRequest, NextResponse } from "next/server";

/**
 * Server-side proxy to the FastAPI backend.
 *
 * The browser never sees the backend address or the API key: it calls /api/..., and this route adds the
 * X-API-Key header from a server-only environment variable. Only the routes the UI needs are forwarded.
 */
export const dynamic = "force-dynamic";

const BACKEND = (process.env.API_BASE_URL ?? "http://localhost:8000").replace(/\/+$/, "");
const API_KEY = process.env.API_KEY ?? "";

// first path segment -> methods the UI may use on it
const ALLOWED: Record<string, string[]> = {
  cases: ["GET", "POST"],
  metrics: ["GET"],
  samples: ["GET"],
};

async function forward(req: NextRequest, { params }: { params: { path: string[] } }) {
  const segments = params.path ?? [];
  const methods = ALLOWED[segments[0]];
  if (!methods || !methods.includes(req.method)) {
    return NextResponse.json({ detail: "Not found" }, { status: 404 });
  }
  if (segments.some((s) => s === ".." || s === "." || s.includes("/") || s.includes("\\"))) {
    return NextResponse.json({ detail: "Bad path" }, { status: 400 });
  }

  const url = `${BACKEND}/${segments.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;
  const headers: Record<string, string> = { Accept: "application/json" };
  if (API_KEY) headers["X-API-Key"] = API_KEY;
  const init: RequestInit = { method: req.method, headers, cache: "no-store" };
  if (req.method === "POST") {
    headers["Content-Type"] = "application/json";
    init.body = await req.text();
  }

  try {
    const res = await fetch(url, { ...init, signal: AbortSignal.timeout(120_000) });
    const text = await res.text();
    return new NextResponse(text, {
      status: res.status,
      headers: { "Content-Type": res.headers.get("content-type") ?? "application/json" },
    });
  } catch {
    return NextResponse.json(
      { detail: `The backend at ${BACKEND} is not reachable. Is the API running?` },
      { status: 502 },
    );
  }
}

export { forward as GET, forward as POST };
