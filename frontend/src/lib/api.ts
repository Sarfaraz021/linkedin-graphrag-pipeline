const API_BASE = import.meta.env.VITE_API_BASE ?? "";

export type GraphStats = {
  people: number;
  posts: number;
  companies: number;
  chunks: number;
  comments: number;
  reactions: number;
  mentions: number;
};

export type Source = {
  text?: string;
  score?: number;
  postId?: string;
  authorName?: string;
  source?: string;
};

export type ChatResult = {
  answer: string;
  sources: Source[];
  graph_stats: GraphStats;
  retrieval_mode: string;
};

export async function fetchStats(): Promise<GraphStats> {
  const res = await fetch(`${API_BASE}/api/stats`);
  if (!res.ok) throw new Error("Failed to load stats");
  return res.json();
}

const SESSION_STORAGE_KEY = "graphrag_session_id";

function getSessionId(): string {
  let sessionId = localStorage.getItem(SESSION_STORAGE_KEY);
  if (!sessionId) {
    sessionId =
      typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `session-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    localStorage.setItem(SESSION_STORAGE_KEY, sessionId);
  }
  return sessionId;
}

export async function sendMessage(message: string): Promise<ChatResult> {
  const res = await fetch(`${API_BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, session_id: getSessionId() }),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || "Chat request failed");
  }
  return res.json();
}
