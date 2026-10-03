import { useState, useRef, useEffect } from "react";
import { T } from "../theme/tokens";
import { chatCopilot } from "../api/endpoints";
import { useAppStore } from "../stores/useAppStore";

interface Widget {
  type: string;
  data: unknown;
}

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  widgets?: Widget[];
}

function widgetValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (Array.isArray(value)) return `${value.length} itens`;
  if (typeof value === "object") return Object.keys(value as Record<string, unknown>).join(", ");
  return String(value);
}

function WidgetView({ data }: { data: unknown }) {
  if (Array.isArray(data) && data.length > 0 && typeof data[0] === "object") {
    const rows = data.slice(0, 8) as Record<string, unknown>[];
    const columns = Object.keys(rows[0]).slice(0, 5);
    return (
      <div style={{ overflow: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 10 }}>
          <thead>
            <tr>{columns.map((column) => <th key={column} style={{ padding: "4px 6px", textAlign: "left", color: T.tertiary, borderBottom: `1px solid ${T.border}` }}>{column}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={index}>{columns.map((column) => <td key={column} style={{ padding: "4px 6px", color: T.secondary, borderBottom: `1px solid ${T.border}` }}>{widgetValue(row[column])}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  if (data && typeof data === "object") {
    return (
      <div style={{ display: "grid", gap: 4 }}>
        {Object.entries(data as Record<string, unknown>).slice(0, 12).map(([key, value]) => (
          <div key={key} style={{ display: "flex", justifyContent: "space-between", gap: 12, fontSize: 10 }}>
            <span style={{ color: T.tertiary }}>{key}</span>
            <span style={{ color: T.secondary, textAlign: "right" }}>{widgetValue(value)}</span>
          </div>
        ))}
      </div>
    );
  }
  return <span style={{ fontSize: 11, color: T.secondary }}>{widgetValue(data)}</span>;
}

export function ChatPanel() {
  const toggleChat = useAppStore((s) => s.toggleChat);
  const [messages, setMessages] = useState<Message[]>([
    { id: crypto.randomUUID(), role: "assistant", content: "Olá. Posso ajudar a analisar a produção, testar cenários ou explicar o plano." },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = async () => {
    if (!input.trim() || loading) return;
    const userMsg: Message = { id: crypto.randomUUID(), role: "user", content: input.trim() };
    const updated = [...messages, userMsg];
    setMessages(updated);
    setInput("");
    setLoading(true);

    try {
      const res = await chatCopilot(updated.map((m) => ({ role: m.role, content: m.content })));
      setMessages((prev) => [...prev, {
        id: crypto.randomUUID(),
        role: "assistant",
        content: res.response,
        widgets: res.widgets?.length ? res.widgets as Widget[] : undefined,
      }]);
    } catch {
      setMessages((prev) => [...prev, { id: crypto.randomUUID(), role: "assistant", content: "Erro ao contactar o copilot." }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <aside
      style={{
        width: 360,
        flexShrink: 0,
        background: T.card,
        borderLeft: `1px solid ${T.border}`,
        display: "flex",
        flexDirection: "column",
      }}
    >
      <div
        style={{
          padding: "14px 20px",
          borderBottom: `1px solid ${T.border}`,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <span style={{ fontSize: 14, fontWeight: 600, color: T.primary }}>Copilot</span>
        <button
          onClick={toggleChat}
          style={{ background: "none", border: "none", color: T.tertiary, cursor: "pointer", fontSize: 16, fontFamily: "inherit" }}
        >
          ×
        </button>
      </div>

      <div style={{ flex: 1, padding: 20, overflowY: "auto", display: "flex", flexDirection: "column", gap: 12 }}>
        {messages.map((m) => (
          <div
            key={m.id}
            style={{
              background: m.role === "user" ? `${T.blue}0D` : T.elevated,
              borderRadius: m.role === "user" ? "14px 14px 4px 14px" : "14px 14px 14px 4px",
              padding: "12px 16px",
              maxWidth: "85%",
              alignSelf: m.role === "user" ? "flex-end" : "flex-start",
            }}
          >
            <p style={{ fontSize: 13, color: m.role === "user" ? T.blue : T.secondary, lineHeight: 1.6, margin: 0, whiteSpace: "pre-wrap" }}>
              {m.content}
            </p>
            {m.widgets?.map((w, wi) => (
              <div
                key={`${m.id}-${wi}`}
                style={{
                  marginTop: 8,
                  padding: "8px 10px",
                  background: T.card,
                  borderRadius: 8,
                  border: `1px solid ${T.border}`,
                }}
              >
                <div style={{ fontSize: 10, color: T.tertiary, fontWeight: 600, textTransform: "uppercase", marginBottom: 4 }}>
                  {w.type}
                </div>
                <WidgetView data={w.data} />
              </div>
            ))}
          </div>
        ))}
        {loading && (
          <div style={{ background: T.elevated, borderRadius: "14px 14px 14px 4px", padding: "12px 16px", maxWidth: "85%" }}>
            <span style={{ fontSize: 13, color: T.tertiary }}>...</span>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div style={{ padding: "12px 20px", borderTop: `1px solid ${T.border}` }}>
        <div style={{ display: "flex", gap: 8 }}>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
            placeholder="Perguntar..."
            style={{
              flex: 1,
              background: T.elevated,
              border: `1px solid ${T.border}`,
              color: T.primary,
              borderRadius: 10,
              padding: "10px 14px",
              fontSize: 13,
              fontFamily: "inherit",
              outline: "none",
            }}
          />
          <button
            onClick={send}
            style={{
              background: T.blue,
              border: "none",
              color: "#fff",
              borderRadius: 10,
              width: 38,
              cursor: "pointer",
              fontSize: 15,
              fontWeight: 600,
              fontFamily: "inherit",
            }}
          >
            ↑
          </button>
        </div>
      </div>
    </aside>
  );
}
