import { useState, useRef, useEffect } from "react";
import {
  startGenesisSession,
  sendGenesisMessage,
  synthesizeGenesisDraft,
  lockMasterPlan,
  getGenesisSession,
  importExistingPlan,
} from "../../api/masterplan.js";
import { Toast } from "../shared/Toast";
import { safeMap } from "../../utils/safe";
import { useToast } from "../../utils/useToast";
import GenesisDraftPreview from "./GenesisDraftPreview";

// Genesis progress lives server-side, but the session id is what lets us find it again after
// a navigation. Persist it so returning to the page resumes instead of starting over.
const SESSION_STORAGE_KEY = "aindy.genesis.session_id";

function readStoredSessionId() {
  try {
    const raw = window.localStorage.getItem(SESSION_STORAGE_KEY);
    return raw ? Number(raw) || null : null;
  } catch {
    return null; // storage blocked (private mode / embedded) — resume simply won't apply
  }
}

function writeStoredSessionId(sessionId) {
  try {
    if (sessionId == null) window.localStorage.removeItem(SESSION_STORAGE_KEY);
    else window.localStorage.setItem(SESSION_STORAGE_KEY, String(sessionId));
  } catch {
    /* non-fatal: resume is a convenience, not a requirement */
  }
}

// The transcript is not persisted server-side (genesis_sessions stores only the distilled
// state), so a resumed session cannot replay the conversation. Say what IS known rather than
// pretending the chat is still there.
function buildResumeMessage(state) {
  const known = [
    ["Vision", state?.vision_summary],
    ["Horizon", state?.time_horizon],
    ["Mechanism", state?.mechanism_summary],
    ["Assets", state?.assets_summary],
  ].filter(([, value]) => value);

  if (!known.length) {
    return "Session resumed. Nothing captured yet — what do you want your life to look like in 5–10 years?";
  }
  const lines = safeMap(known, ([label, value]) => `${label}: ${value}`).join("\n");
  return `Session resumed. Here is what I have so far:\n\n${lines}\n\nPick up where we left off — or refine any of the above.`;
}

// Restore the real conversation when the server has one. `buildResumeMessage` is the
// fallback for sessions that predate transcript persistence — their dialogue was only
// ever held in React state and is genuinely gone, so the six-field summary is the most
// that can honestly be shown.
function restoreMessages(data) {
  const transcript = Array.isArray(data?.transcript) ? data.transcript : [];
  if (transcript.length) {
    return safeMap(transcript, (entry) => ({
      role: entry.role === "assistant" ? "ai" : "user",
      content: entry.content,
    }));
  }
  return [{ role: "ai", content: buildResumeMessage(data?.summarized_state) }];
}

export default function Genesis() {
  const [started, setStarted] = useState(false);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [resuming, setResuming] = useState(true);
  const [sessionId, setSessionId] = useState(null);
  const [synthesisReady, setSynthesisReady] = useState(false);
  const [synthesizing, setSynthesizing] = useState(false);
  const [draft, setDraft] = useState(null);
  const [locking, setLocking] = useState(false);
  const [lockedPlan, setLockedPlan] = useState(null);
  const [importing, setImporting] = useState(false);
  const [importText, setImportText] = useState("");
  const { toast, showToast, clearToast } = useToast();

  const bottomRef = useRef(null);

  // Resume an in-progress session on mount. Uses a GET, so simply visiting Genesis never
  // creates a session — only the explicit Initialize action does.
  useEffect(() => {
    let mounted = true;
    (async () => {
      const storedId = readStoredSessionId();
      try {
        if (!storedId) return;
        const data = await getGenesisSession(storedId);
        if (!mounted) return;
        if (data?.status !== "active") {
          writeStoredSessionId(null); // finished or abandoned — start fresh next time
          return;
        }
        setSessionId(data.session_id);
        setSynthesisReady(Boolean(data.synthesis_ready));
        setStarted(true);
        setMessages(restoreMessages(data));
      } catch {
        writeStoredSessionId(null); // stale/foreign id — fall back to the start screen
      } finally {
        if (mounted) setResuming(false);
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);

  // Import lands the user *in the conversation*, not on a finished plan: the whole point
  // of accepting free text is that an existing plan can be discussed before it is locked.
  const importPlan = async () => {
    setLoading(true);
    try {
      const data = await importExistingPlan(importText.trim());
      setSessionId(data.session_id);
      writeStoredSessionId(data.session_id);
      setSynthesisReady(Boolean(data.synthesis_ready));
      setStarted(true);
      setImporting(false);
      setImportText("");
      setMessages(restoreMessages(data));
    } catch (err) {
      showToast(
        err?.data?.detail?.message || err?.message || "Could not read that plan."
      );
    } finally {
      setLoading(false);
    }
  };

  const startGenesis = async () => {
    setLoading(true);
    try {
      // Idempotent server-side: returns the active session if one is already in progress.
      const data = await startGenesisSession();
      setSessionId(data.session_id);
      writeStoredSessionId(data.session_id);
      setSynthesisReady(Boolean(data.synthesis_ready));
      setStarted(true);
      setMessages(
        data.resumed
          ? restoreMessages(data)
          : [
              {
                role: "ai",
                content:
                  "Initialization sequence active. I have established a secure session. What do you want your life to look like in 5–10 years?",
              },
            ]
      );
    } catch (err) {
      console.error("Failed to start session:", err);
      showToast(err?.message || "A.I.N.D.Y. connection error. Ensure the backend is running and you are logged in.");
    } finally {
      setLoading(false);
    }
  };

  const scrollToBottom = () => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!input.trim() || loading) return;

    const userMessage = { role: "user", content: input.trim() };
    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setLoading(true);

    try {
      const data = await sendGenesisMessage(sessionId, userMessage.content);

      if (data.synthesis_ready && !synthesisReady) {
        setSynthesisReady(true);
      }

      setTimeout(() => {
        setMessages((prev) => [...prev, { role: "ai", content: data.reply }]);
        setLoading(false);
      }, 600);
    } catch (err) {
      console.error(err);
      showToast(err?.message || "Genesis message failed. Please try again.");
      setMessages((prev) => [
      ...prev,
      { role: "ai", content: "Protocol error. Sync failed. Please try again." }]
      );
      setLoading(false);
    }
  };

  const handleSynthesize = async () => {
    setSynthesizing(true);
    try {
      const data = await synthesizeGenesisDraft(sessionId);
      setDraft(data.draft);
      setMessages((prev) => [
      ...prev,
      {
        role: "ai",
        content:
        "Draft MasterPlan synthesized. Review it below and lock it when ready."
      }]
      );
    } catch (err) {
      console.error(err);
      showToast(err?.message || "Synthesis failed.");
    } finally {
      setSynthesizing(false);
    }
  };

  const handleLock = async () => {
    if (!draft) return;
    setLocking(true);
    try {
      const data = await lockMasterPlan(sessionId, draft);
      setLockedPlan(data);
      // Session is finished — don't offer to resume it on the next visit.
      writeStoredSessionId(null);
      setMessages((prev) => [
      ...prev,
      {
        role: "ai",
        content: `MasterPlan ${data.version} locked. Posture: ${data.posture}. The plan is now permanent.`
      }]
      );
    } catch (err) {
      console.error(err);
      showToast(err?.message || "Lock failed.");
    } finally {
      setLocking(false);
    }
  };

  return (
    <div className="min-h-screen flex justify-center bg-[#09090b] text-zinc-100">
      <div className="w-full max-w-2xl px-6 py-16 flex flex-col">
        {!started ?
        <div className="text-center space-y-8 my-auto">
            <div className="space-y-4">
              <h1 className="text-4xl font-bold tracking-tighter text-white">
                PROJECT <span className="text-[#00ffaa]">GENESIS</span>
              </h1>
              <p className="text-zinc-500 max-w-sm mx-auto">
                Define your long-term strategic direction. A.I.N.D.Y. is ready to architect your MasterPlan.
              </p>
            </div>
            <button
            onClick={startGenesis}
            disabled={loading || resuming}
            className="px-8 py-4 bg-white text-black font-bold rounded-lg hover:bg-[#00ffaa] transition-colors shadow-[0_0_20px_rgba(255,255,255,0.1)] disabled:opacity-50">

              {resuming ? "RESTORING SESSION..." : loading ? "ESTABLISHING LINK..." : "INITIALIZE"}
            </button>

            <div className="pt-2">
              {!importing ?
              <button
                type="button"
                onClick={() => setImporting(true)}
                disabled={loading || resuming}
                className="text-xs text-zinc-500 hover:text-zinc-300 underline underline-offset-4 disabled:opacity-40">
                  Already have a plan written? Import it
                </button> :
              <div className="space-y-3 text-left">
                  <p className="text-xs text-zinc-500">
                    Paste it in whatever form it is in. A.I.N.D.Y. will read it, tell you what it
                    took from it and what is still missing, and you carry on from there.
                  </p>
                  <textarea
                  value={importText}
                  onChange={(e) => setImportText(e.target.value)}
                  rows={8}
                  placeholder="Paste your existing plan..."
                  className="w-full rounded-lg border border-zinc-800 bg-zinc-900/70 px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-600" />

                  <div className="flex gap-2">
                    <button
                    type="button"
                    onClick={importPlan}
                    disabled={loading || !importText.trim()}
                    className="px-4 py-2 bg-white text-black text-sm font-bold rounded-lg hover:bg-[#00ffaa] transition-colors disabled:opacity-40">
                      {loading ? "READING..." : "IMPORT"}
                    </button>
                    <button
                    type="button"
                    onClick={() => { setImporting(false); setImportText(""); }}
                    className="px-4 py-2 text-sm text-zinc-400 hover:text-zinc-200">
                      Cancel
                    </button>
                  </div>
                </div>
              }
            </div>
          </div> :

        <>
            {/* CHAT STREAM */}
            <div className="flex-1 space-y-6 mb-6 overflow-y-auto pr-2 custom-scrollbar">
              {safeMap(messages, (msg, index) =>
            <div
              key={index}
              className={`flex ${msg.role === "ai" ? "justify-start" : "justify-end"}`}>
              
                  <div
                className={`max-w-[85%] px-5 py-4 rounded-xl text-sm leading-relaxed ${
                msg.role === "ai" ?
                "bg-zinc-900 border border-zinc-800 text-zinc-200" :
                "bg-[#00ffaa] text-black font-bold shadow-[0_0_15px_rgba(0,255,170,0.2)]"}`
                }>
                
                    {msg.content}
                  </div>
                </div>)
            }
              {loading &&
            <div className="flex justify-start">
                  <div className="bg-zinc-900 border border-zinc-800 text-zinc-500 px-5 py-3 rounded-xl text-xs animate-pulse">
                    A.I.N.D.Y. is thinking...
                  </div>
                </div>
            }
              <div ref={bottomRef} />
            </div>

            {/* SYNTHESIS READY BANNER */}
            {synthesisReady && !draft &&
          <div className="mb-4 p-4 rounded-xl border border-[#00ffaa]/40 bg-[#00ffaa]/5 flex items-center justify-between">
                <div>
                  <p className="text-[#00ffaa] font-bold text-sm">SYNTHESIS READY</p>
                  <p className="text-zinc-400 text-xs mt-1">
                    A.I.N.D.Y. has enough context to generate your MasterPlan draft.
                  </p>
                </div>
                <button
              onClick={handleSynthesize}
              disabled={synthesizing}
              className="px-4 py-2 bg-[#00ffaa] text-black font-bold rounded-lg text-sm disabled:opacity-50 hover:brightness-110 transition-all">
              
                  {synthesizing ? "SYNTHESIZING..." : "SYNTHESIZE"}
                </button>
              </div>
          }

            {/* DRAFT PREVIEW — rich editable preview + Strategic Integrity Audit */}
            {draft && !lockedPlan &&
          <div className="mb-4">
                <GenesisDraftPreview
              draft={draft}
              sessionId={sessionId}
              onLock={handleLock}
              locking={locking} />

              </div>
          }

            {/* LOCKED CONFIRMATION */}
            {lockedPlan &&
          <div className="mb-4 p-4 rounded-xl border border-[#00ffaa]/60 bg-[#00ffaa]/10 text-center">
                <p className="text-[#00ffaa] font-bold">MASTERPLAN LOCKED</p>
                <p className="text-zinc-400 text-xs mt-1">
                  {lockedPlan.version} · Posture: {lockedPlan.posture}
                </p>
              </div>
          }

            {/* INPUT FORM */}
            {!lockedPlan &&
          <form onSubmit={handleSubmit} className="mt-auto relative">
                <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                // Enter sends; Shift+Enter inserts a newline. A <textarea> inside a
                // <form> does NOT submit on Enter the way an <input> does, so without
                // this the SEND button was the only way to send a message (walk-log
                // item 2). Guard on isComposing so an IME candidate selection — which
                // also fires Enter — does not send a half-typed message.
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  handleSubmit(e);
                }
              }}
              rows={2}
              disabled={loading}
              placeholder="Transmitting signal..."
              className="w-full bg-zinc-900 border border-zinc-800 rounded-xl p-4 text-white resize-none focus:outline-hidden focus:border-[#00ffaa]/50 transition-all placeholder-zinc-600" />
            
                <button
              type="submit"
              disabled={loading}
              className="absolute right-3 bottom-3 px-5 py-2 bg-white text-black font-bold rounded-lg disabled:opacity-50 hover:bg-[#00ffaa] transition-all">
              
                  {loading ? "..." : "SEND"}
                </button>
              </form>
          }
          </>
        }
      </div>

      <style>{`
        .custom-scrollbar::-webkit-scrollbar { width: 4px; }
        .custom-scrollbar::-webkit-scrollbar-track { background: transparent; }
        .custom-scrollbar::-webkit-scrollbar-thumb { background: #27272a; border-radius: 10px; }
      `}</style>
      <Toast toast={toast} onDismiss={clearToast} />
    </div>);

}
