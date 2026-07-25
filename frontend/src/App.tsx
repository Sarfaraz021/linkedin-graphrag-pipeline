import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ChatResult, GraphStats, fetchStats, sendMessage } from "./lib/api";

type Message = {
  role: "user" | "assistant";
  content: string;
  meta?: ChatResult;
};

const SUGGESTIONS = [
  "Who commented on the post and what did they say?",
  "Summarize the post engagement and key themes.",
  "Which companies and awards were mentioned?",
  "Who are the most active commenters?",
];

export default function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [stats, setStats] = useState<GraphStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetchStats()
      .then(setStats)
      .catch(() => setStats(null));
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  async function handleSend(text: string) {
    const question = text.trim();
    if (!question || loading) return;
    setError(null);
    setInput("");
    setMessages((m) => [...m, { role: "user", content: question }]);
    setLoading(true);
    try {
      const result = await sendMessage(question);
      setStats(result.graph_stats);
      setMessages((m) => [
        ...m,
        { role: "assistant", content: result.answer, meta: result },
      ]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="app">
      <header className="header">
        <div>
          <p className="eyebrow">Neo4j GraphRAG · LinkedIn Knowledge Graph</p>
          <h1>Engagement Intelligence Demo</h1>
          <p className="subtitle">Ask natural-language questions over posts, people, comments, and vector embeddings.</p>
        </div>
        {stats && (
          <div className="stats">
            <Stat label="People" value={stats.people} />
            <Stat label="Posts" value={stats.posts} />
            <Stat label="Comments" value={stats.comments} />
            <Stat label="Chunks" value={stats.chunks} />
          </div>
        )}
      </header>

      <main className="chat-shell">
        <section className="messages">
          {messages.length === 0 && (
            <div className="empty">
              <h2>Try a question</h2>
              <div className="chips">
                {SUGGESTIONS.map((s) => (
                  <button key={s} className="chip" onClick={() => handleSend(s)}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((msg, i) => (
            <article key={i} className={`bubble ${msg.role}`}>
              <div className="bubble-label">{msg.role === "user" ? "You" : "GraphRAG"}</div>
              {msg.role === "assistant" ? (
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
              ) : (
                <p>{msg.content}</p>
              )}
              {msg.meta && (
                <div className="meta">
                  <span className="badge">{msg.meta.retrieval_mode}</span>
                  {msg.meta.sources?.slice(0, 3).map((s, idx) => (
                    <span key={idx} className="source-tag">
                      {s.postId ? `post ${s.postId}` : s.source ?? "context"}
                    </span>
                  ))}
                </div>
              )}
            </article>
          ))}

          {loading && (
            <article className="bubble assistant loading">
              <div className="bubble-label">GraphRAG</div>
              <div className="dots"><span /><span /><span /></div>
            </article>
          )}
          <div ref={bottomRef} />
        </section>

        <footer className="composer">
          {error && <div className="error">{error}</div>}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleSend(input);
            }}
          >
            <textarea
              rows={2}
              placeholder="Ask about engagement, commenters, companies, awards, topics..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSend(input);
                }
              }}
            />
            <button type="submit" disabled={loading || !input.trim()}>
              {loading ? "Thinking..." : "Ask"}
            </button>
          </form>
        </footer>
      </main>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="stat">
      <span className="stat-value">{value.toLocaleString()}</span>
      <span className="stat-label">{label}</span>
    </div>
  );
}
