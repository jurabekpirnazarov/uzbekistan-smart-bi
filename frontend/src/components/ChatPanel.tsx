import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { chatStatus, streamChat, type ChatTurn } from "../api/client";

interface Message extends ChatTurn {
  tools?: string[];
  error?: string;
  streaming?: boolean;
}

const EXAMPLES = [
  "Where should I open a pharmacy in Fergana region?",
  "Toshkent viloyatida qaysi tumanlarda biznes eng tez o‘smoqda?",
  "Сравни Самарканд и Бухару по населению и услугам.",
  "Which regions grew fastest in market services since 2020?",
];

export function ChatPanel({
  open,
  onClose,
  initialQuestion,
}: {
  open: boolean;
  onClose: () => void;
  initialQuestion?: string;
}) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<{ enabled: boolean; model: string | null } | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    chatStatus()
      .then(setStatus)
      .catch(() => setStatus({ enabled: false, model: null }));
  }, []);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  const askedInitial = useRef(false);
  useEffect(() => {
    if (status?.enabled && initialQuestion && !askedInitial.current) {
      askedInitial.current = true;
      void send(initialQuestion);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, initialQuestion]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages]);

  const updateLast = (fn: (m: Message) => Message) =>
    setMessages((prev) => [...prev.slice(0, -1), fn(prev[prev.length - 1])]);

  const send = async (text: string) => {
    const q = text.trim();
    if (!q || busy) return;
    const history: ChatTurn[] = [
      ...messages.filter((m) => !m.error && m.content).map(({ role, content }) => ({ role, content })),
      { role: "user", content: q },
    ];
    setMessages((prev) => [...prev, { role: "user", content: q }, { role: "assistant", content: "", tools: [], streaming: true }]);
    setInput("");
    setBusy(true);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      await streamChat(
        history,
        {
          onToken: (t) => updateLast((m) => ({ ...m, content: m.content + t })),
          onToolCall: (tool) => updateLast((m) => ({ ...m, tools: [...(m.tools ?? []), tool.label] })),
          onError: (message) => updateLast((m) => ({ ...m, error: message })),
          onDone: () => undefined,
        },
        ctrl.signal,
      );
    } catch (e) {
      if (!ctrl.signal.aborted) updateLast((m) => ({ ...m, error: String(e) }));
    } finally {
      updateLast((m) => ({ ...m, streaming: false }));
      setBusy(false);
      abortRef.current = null;
    }
  };

  return (
    <aside className={`chat ${open ? "open" : ""}`} aria-label="AI analyst" aria-hidden={!open}>
      <header className="chat-head">
        <div>
          <h2>AI analyst</h2>
          <p className="muted small-inline">
            {status?.enabled ? `Official SIAT data · ${status.model}` : "AI is not configured (OPENAI_API_KEY)"}
          </p>
        </div>
        <div className="chat-actions">
          {messages.length > 0 && (
            <button type="button" className="link" onClick={() => setMessages([])} disabled={busy}>
              New chat
            </button>
          )}
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Close chat">
            ×
          </button>
        </div>
      </header>

      <div className="chat-body" ref={scrollRef}>
        {messages.length === 0 && (
          <div className="chat-empty">
            <p>
              Ask about population, businesses and services in any region or district — in English, O‘zbekcha or
              Русский. Every number comes from official SIAT statistics.
            </p>
            <div className="chips">
              {EXAMPLES.map((e) => (
                <button key={e} type="button" className="chip" onClick={() => send(e)} disabled={!status?.enabled}>
                  {e}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            {m.role === "assistant" && m.tools && m.tools.length > 0 && (
              <div className="tool-chips">
                {[...new Set(m.tools)].map((t) => (
                  <span key={t} className="tool-chip">
                    {t}
                    {countOf(m.tools!, t) > 1 ? ` ×${countOf(m.tools!, t)}` : ""}
                  </span>
                ))}
              </div>
            )}
            {m.role === "assistant" ? (
              <div className="md">
                {m.content ? (
                  <Markdown remarkPlugins={[remarkGfm]} components={{ a: (p) => <a {...p} target="_blank" rel="noreferrer" /> }}>
                    {m.content}
                  </Markdown>
                ) : (
                  m.streaming && !m.error && <span className="typing">Analysing official data…</span>
                )}
              </div>
            ) : (
              <p>{m.content}</p>
            )}
            {m.error && <div className="alert">{m.error}</div>}
          </div>
        ))}
      </div>

      <form
        className="chat-input"
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
      >
        <textarea
          ref={inputRef}
          value={input}
          rows={2}
          placeholder={status?.enabled ? "Ask about any region or district…" : "AI is not configured"}
          disabled={!status?.enabled}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send(input);
            }
          }}
        />
        {busy ? (
          <button type="button" onClick={() => abortRef.current?.abort()}>
            Stop
          </button>
        ) : (
          <button type="submit" disabled={!input.trim() || !status?.enabled}>
            Send
          </button>
        )}
      </form>
      <p className="chat-note muted">AI interpretation is decision support, not a guarantee. Check the cited sources.</p>
    </aside>
  );
}

function countOf(list: string[], item: string): number {
  return list.filter((x) => x === item).length;
}
