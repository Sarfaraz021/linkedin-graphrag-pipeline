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
  {
    title: "Comment analysis",
    text: "Who commented on the post and what did they say?",
    icon: "chat",
  },
  {
    title: "Engagement summary",
    text: "Summarize the post engagement and key themes.",
    icon: "chart",
  },
  {
    title: "Entity discovery",
    text: "Which companies and awards were mentioned?",
    icon: "search",
  },
  {
    title: "Top contributors",
    text: "Who are the most active commenters?",
    icon: "users",
  },
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
      <header className="app-header">
        <div className="header-brand">
          <div className="logo">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
              <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="1.5" />
              <circle cx="8" cy="10" r="2" fill="currentColor" />
              <circle cx="16" cy="10" r="2" fill="currentColor" />
              <circle cx="12" cy="16" r="2" fill="currentColor" />
              <line x1="8" y1="10" x2="12" y2="16" stroke="currentColor" strokeWidth="1.2" />
              <line x1="16" y1="10" x2="12" y2="16" stroke="currentColor" strokeWidth="1.2" />
              <line x1="8" y1="10" x2="16" y2="10" stroke="currentColor" strokeWidth="1.2" />
            </svg>
          </div>
          <div>
            <h1 className="header-title">LinkedIn Graph Intelligence</h1>
            <p className="header-sub">Hybrid knowledge graph · Neo4j GraphRAG</p>
          </div>
        </div>

        {stats && (
          <div className="header-stats">
            <StatPill label="People" value={stats.people} />
            <StatPill label="Posts" value={stats.posts} />
            <StatPill label="Comments" value={stats.comments} />
            <StatPill label="Vectors" value={stats.chunks} />
          </div>
        )}

        <div className="header-status">
          <span className="status-indicator" />
          <span>Neo4j Aura</span>
        </div>
      </header>

      <div className="app-body">
        <aside className="panel panel-left">
          <div className="panel-block">
            <h2 className="panel-heading">Quick prompts</h2>
            <div className="prompt-list">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s.text}
                  className="prompt-card"
                  onClick={() => handleSend(s.text)}
                  disabled={loading}
                >
                  <span className="prompt-icon">
                    <PromptIcon name={s.icon} />
                  </span>
                  <span className="prompt-text">
                    <span className="prompt-title">{s.title}</span>
                    <span className="prompt-desc">{s.text}</span>
                  </span>
                  <svg className="prompt-arrow" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M5 12h14M13 6l6 6-6 6" />
                  </svg>
                </button>
              ))}
            </div>
          </div>

          <div className="panel-block panel-info">
            <h2 className="panel-heading">How it works</h2>
            <ul className="info-list">
              <li>
                <strong>Backbone layer</strong> — People, posts, and social edges merged on stable LinkedIn IDs.
              </li>
              <li>
                <strong>Semantic layer</strong> — LLM extracts companies, awards, topics, and skills from text.
              </li>
              <li>
                <strong>Vector search</strong> — GraphRAG retrieves relevant chunks to answer your question.
              </li>
            </ul>
          </div>
        </aside>

        <main className="panel panel-main">
          <div className="chat-scroll">
            <div className="chat-thread">
              {messages.length === 0 && !loading && (
                <div className="empty-state">
                  <div className="empty-icon">
                    <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                    </svg>
                  </div>
                  <h2>Engagement Analyst</h2>
                  <p>
                    Ask natural-language questions about LinkedIn post engagement,
                    commenters, companies, and semantic entities in your knowledge graph.
                  </p>
                  <div className="empty-prompts">
                    {SUGGESTIONS.map((s) => (
                      <button
                        key={s.text}
                        className="empty-prompt"
                        onClick={() => handleSend(s.text)}
                        disabled={loading}
                      >
                        {s.text}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {messages.map((msg, i) => (
                <div key={i} className={`bubble-row ${msg.role}`}>
                  {msg.role === "assistant" && (
                    <div className="bubble-avatar assistant">
                      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M12 2a4 4 0 0 1 4 4v1h1a3 3 0 0 1 3 3v8a3 3 0 0 1-3 3H7a3 3 0 0 1-3-3v-8a3 3 0 0 1 3-3h1V6a4 4 0 0 1 4-4z" />
                        <circle cx="9" cy="13" r="1" fill="currentColor" />
                        <circle cx="15" cy="13" r="1" fill="currentColor" />
                      </svg>
                    </div>
                  )}
                  <div className="bubble-wrap">
                    <div className="bubble-label">
                      {msg.role === "user" ? "You" : "GraphRAG Assistant"}
                    </div>
                    <div className={`bubble ${msg.role}`}>
                      {msg.role === "assistant" ? (
                        <div className="markdown-body">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
                        </div>
                      ) : (
                        <p>{msg.content}</p>
                      )}
                    </div>
                    {msg.meta && (
                      <div className="bubble-sources">
                        <span className="source-tag mode">{msg.meta.retrieval_mode}</span>
                        {msg.meta.sources?.slice(0, 4).map((s, idx) => (
                          <span key={idx} className="source-tag">
                            {s.postId ? `Post · ${s.postId.slice(0, 10)}…` : s.source ?? "context"}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                  {msg.role === "user" && (
                    <div className="bubble-avatar user">You</div>
                  )}
                </div>
              ))}

              {loading && (
                <div className="bubble-row assistant">
                  <div className="bubble-avatar assistant">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M12 2a4 4 0 0 1 4 4v1h1a3 3 0 0 1 3 3v8a3 3 0 0 1-3 3H7a3 3 0 0 1-3-3v-8a3 3 0 0 1 3-3h1V6a4 4 0 0 1 4-4z" />
                    </svg>
                  </div>
                  <div className="bubble-wrap">
                    <div className="bubble-label">GraphRAG Assistant</div>
                    <div className="bubble assistant loading-bubble">
                      <div className="dots">
                        <span /><span /><span />
                      </div>
                      <span className="loading-text">Searching knowledge graph…</span>
                    </div>
                  </div>
                </div>
              )}
              <div ref={bottomRef} />
            </div>
          </div>

          <div className="composer-area">
            {error && <div className="error-toast">{error}</div>}
            <form
              className="composer-form"
              onSubmit={(e) => {
                e.preventDefault();
                handleSend(input);
              }}
            >
              <div className="composer-field">
                <textarea
                  rows={1}
                  placeholder="Ask about commenters, engagement, companies, awards, topics…"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      handleSend(input);
                    }
                  }}
                />
                <button type="submit" className="send-btn" disabled={loading || !input.trim()}>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z" />
                  </svg>
                  <span>{loading ? "Analyzing" : "Send"}</span>
                </button>
              </div>
              <p className="composer-note">Press Enter to send · Shift+Enter for new line</p>
            </form>
          </div>
        </main>
      </div>
    </div>
  );
}

function StatPill({ label, value }: { label: string; value: number }) {
  return (
    <div className="stat-pill">
      <span className="stat-pill-value">{value.toLocaleString()}</span>
      <span className="stat-pill-label">{label}</span>
    </div>
  );
}

function PromptIcon({ name }: { name: string }) {
  switch (name) {
    case "chat":
      return (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
        </svg>
      );
    case "chart":
      return (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M18 20V10M12 20V4M6 20v-6" />
        </svg>
      );
    case "search":
      return (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="11" cy="11" r="8" />
          <path d="M21 21l-4.35-4.35" />
        </svg>
      );
    case "users":
      return (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
          <circle cx="9" cy="7" r="4" />
          <path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" />
        </svg>
      );
    default:
      return null;
  }
}
