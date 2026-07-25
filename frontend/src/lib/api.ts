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

export async function sendMessage(message: string): Promise<ChatResult> {
  const res = await fetch(`${API_BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || "Chat request failed");
  }
  return res.json();
}
