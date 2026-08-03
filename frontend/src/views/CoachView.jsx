import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useTypewriter } from "../useTypewriter";

// The reply currently arriving. Older messages render as plain text — replaying
// the animation on every re-render would retype history the user already read.
function StreamingReply({ text }) {
  const { text: shown, typing } = useTypewriter(text);
  return (
    <div className="chat-content">
      {shown}
      {typing && <span className="caret" aria-hidden="true" />}
    </div>
  );
}

export default function CoachView() {
  const [followups, setFollowups] = useState([]);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [streaming, setStreaming] = useState(null);
  const bottomRef = useRef(null);

  useEffect(() => {
    api.followups().then(setFollowups).catch(() => {});
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading, streaming]);

  const pushAndSend = async (userText, sendFn) => {
    const nextMessages = [...messages, { role: "user", content: userText }];
    setMessages(nextMessages);
    setLoading(true);
    try {
      const reply = await sendFn(nextMessages);
      setMessages([...nextMessages, { role: "assistant", content: reply }]);
    } catch (e) {
      setMessages([...nextMessages, { role: "assistant", content: `Couldn't reach Claude: ${e.message}` }]);
    } finally {
      setLoading(false);
      setStreaming(null);
    }
  };

  const analyzeDay = () => pushAndSend("Analyze my day", async () => (await api.analyzeDay()).reply);

  const askFollowup = (question) =>
    pushAndSend(question, async (msgs) => {
      try {
        setStreaming("");
        return await api.chatStream(msgs, setStreaming);
      } catch (e) {
        // Streaming is an enhancement, not the feature — if it fails for any
        // reason other than Claude itself refusing, fall back to the plain
        // request so the user still gets their answer.
        setStreaming(null);
        return (await api.chat(msgs)).reply;
      }
    });

  const sendFreeform = () => {
    if (!input.trim() || loading) return;
    const text = input;
    setInput("");
    askFollowup(text);
  };

  return (
    <div className="view-grid">
      <div className="coach-actions">
        <button className="primary-btn" onClick={analyzeDay} disabled={loading}>
          🔍 Analyze my day
        </button>
      </div>

      <div className="caption">Suggested follow-ups:</div>
      <div className="followup-row">
        {followups.map((q) => (
          <button key={q} className="followup-btn" onClick={() => askFollowup(q)} disabled={loading}>
            {q}
          </button>
        ))}
      </div>

      <div className="chat-log">
        {messages.length === 0 && !loading && (
          <div className="empty-note">Ask a question, or click "Analyze my day" to get started.</div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`chat-message ${m.role}`}>
            <div className="chat-role">{m.role === "user" ? "You" : "Coach"}</div>
            <div className="chat-content">{m.content}</div>
          </div>
        ))}
        {loading && (
          <div className="chat-message assistant">
            <div className="chat-role">Coach</div>
            {streaming ? (
              <StreamingReply text={streaming} />
            ) : (
              <div className="chat-content">
                <span className="typing-dots">
                  <span />
                  <span />
                  <span />
                </span>
              </div>
            )}
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="chat-input-row">
        <input
          type="text"
          placeholder="Ask your coach anything..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && sendFreeform()}
        />
        <button onClick={sendFreeform} disabled={loading}>
          Send
        </button>
      </div>
    </div>
  );
}
