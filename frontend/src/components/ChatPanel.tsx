import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  api,
  chatStatus,
  streamChat,
  type ChatResult,
  type ChatStatus,
  type ChatTurn,
  type MapFocus,
  type Verification,
} from "../api/client";

interface Message extends ChatTurn {
  tools?: string[];
  error?: string;
  streaming?: boolean;
  verification?: Verification;
  result?: ChatResult;
  voted?: 1 | -1;
}

const EXAMPLES = [
  "Where should I open a pharmacy in Fergana region?",
  "Toshkent viloyatida qaysi tumanlarda biznes eng tez o‘smoqda?",
  "Сравни Самарканд и Бухару по населению и услугам.",
  "How is the Business Opportunity Score calculated?",
];

export interface AskRequest {
  id: number;
  text?: string;
}

export function ChatPanel({
  open,
  onClose,
  request,
  onShowMap,
}: {
  open: boolean;
  onClose: () => void;
  request: AskRequest | null;
  onShowMap: (f: MapFocus) => void;
}) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<ChatStatus | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    chatStatus()
      .then(setStatus)
      .catch(() => setStatus({ enabled: false, mode: "fallback", model: null }));
  }, []);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  // a question asked from elsewhere in the app (home page box, ?ask= link)
  const handled = useRef<number | null>(null);
  useEffect(() => {
    if (!request || !status?.enabled || handled.current === request.id) return;
    handled.current = request.id;
    if (request.text) void send(request.text);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [request, status]);

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
          onVerification: (v) => updateLast((m) => ({ ...m, verification: v })),
          onResult: (r) => updateLast((m) => ({ ...m, result: r })),
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

  const vote = (i: number, rating: 1 | -1) => {
    const m = messages[i];
    setMessages((prev) => prev.map((x, j) => (j === i ? { ...x, voted: rating } : x)));
    void api.feedback({ request_id: m.result?.request_id ?? null, target: "chat", rating }).catch(() => undefined);
  };

  const subtitle = !status
    ? "Connecting…"
    : status.mode === "llm"
      ? `Official SIAT data · ${status.model}`
      : "Rule-based mode (no OpenAI key) · official SIAT data";

  return (
    <aside className={`chat ${open ? "open" : ""}`} aria-label="AI analyst" aria-hidden={!open}>
      <header className="chat-head">
        <div>
          <h2>AI analyst</h2>
          <p className="muted small-inline">{subtitle}</p>
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
              Ask about population, businesses, services, forecasts or the best district for a business — in English,
              O‘zbekcha or Русский. Every number comes from official SIAT statistics or a labelled model.
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
                {m.result?.is_synthetic && <div className="banner synthetic">DEMO / SYNTHETIC DATA — not official statistics</div>}
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
            {m.role === "assistant" && !m.streaming && !m.error && m.content && (
              <div className="msg-foot">
                {m.verification &&
                  (m.verification.unsupported.length === 0 ? (
                    <span className="verify ok" title="Every number was found in a tool result">
                      ✓ {m.verification.checked} numbers verified
                    </span>
                  ) : (
                    <span className="verify bad" title="These numbers were not found in any tool result — treat with caution">
                      ⚠ unverified: {m.verification.unsupported.slice(0, 4).join(", ")}
                    </span>
                  ))}
                {m.result?.map_focus && m.result.map_focus.soatos.length > 0 && (
                  <button type="button" className="link" onClick={() => onShowMap(m.result!.map_focus!)}>
                    Show on map
                  </button>
                )}
                <span className="feedback">
                  <button
                    type="button"
                    className={`icon-btn small ${m.voted === 1 ? "on" : ""}`}
                    aria-label="Helpful"
                    disabled={m.voted !== undefined}
                    onClick={() => vote(i, 1)}
                  >
                    👍
                  </button>
                  <button
                    type="button"
                    className={`icon-btn small ${m.voted === -1 ? "on" : ""}`}
                    aria-label="Not helpful"
                    disabled={m.voted !== undefined}
                    onClick={() => vote(i, -1)}
                  >
                    👎
                  </button>
                </span>
              </div>
            )}
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
          placeholder="Ask about any region, district or business…"
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
