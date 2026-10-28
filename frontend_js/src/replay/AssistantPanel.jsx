import { useEffect, useRef, useState } from "react";
import { assistantStatus, askAssistant } from "../api";

const SUGGESTIONS = {
  commander: ["이번 실행에서 SOS는 몇 건이야?", "균형, 정밀, 신속 모드를 비교해줘", "최적화 결과에서 어떤 편성이 좋았어?", "예보 정확도는 어때?"],
  operator: ["우리 제대 SOS는 몇 건이야?", "우리 제대 SOS는 언제 발생했어?", "예보 정확도는 어때?"],
};

// 답변 속 [E1] 을 근거 칩으로 바꾼다. 누르면 해당 도구 결과가 펼쳐진다.
function Answer({ text, onCite }) {
  const parts = text.split(/(\[E\d+\])/g);
  return (
    <p className="ai-text">
      {parts.map((part, i) => {
        const m = /^\[(E\d+)\]$/.exec(part);
        return m ? <button key={i} className="cite" onClick={() => onCite(m[1])}>{m[1]}</button> : part;
      })}
    </p>
  );
}

function Evidence({ ev, open }) {
  return (
    <details className={`ai-ev ${ev.denied ? "denied" : ""} ${ev.error && !ev.denied ? "error" : ""}`} open={open}>
      <summary><span className="cite static">{ev.id}</span>{ev.tool}{ev.denied ? " · 권한 없음" : ev.error ? " · 오류" : ""}</summary>
      <pre>{JSON.stringify(ev.result, null, 1)}</pre>
    </details>
  );
}

// AI 어시스턴트: 질문 → 서버가 도구로 기록을 조회해 근거와 함께 답한다 (읽기 전용).
export default function AssistantPanel({ role }) {
  const [status, setStatus] = useState(null);
  const [items, setItems] = useState([]);      // {q, a?, error?, pending?}
  const [text, setText] = useState("");
  const [openEv, setOpenEv] = useState({});     // `${index}:${E#}` → 펼침
  const endRef = useRef(null);

  useEffect(() => { assistantStatus().then(setStatus).catch(() => setStatus({ enabled: false })); }, []);
  useEffect(() => { endRef.current?.scrollIntoView({ block: "end" }); }, [items]);

  async function send(question) {
    const q = question.trim();
    if (!q || items.some((it) => it.pending)) return;
    setText("");
    setItems((cur) => [...cur, { q, pending: true }]);
    const index = items.length;
    try {
      const a = await askAssistant(q);
      setItems((cur) => cur.map((it, i) => (i === index ? { q, a } : it)));
    } catch (e) {
      setItems((cur) => cur.map((it, i) => (i === index ? { q, error: e.message } : it)));
    }
  }

  if (status && !status.enabled) {
    return (
      <div className="ai-off">
        <b>AI 어시스턴트가 꺼져 있습니다</b>
        <p>서버의 <code>backend/.env</code>에 <code>GEMINI_API_KEY</code>를 넣고 서버를 다시 시작하면 켜집니다.</p>
      </div>
    );
  }

  return (
    <div className="ai">
      <div className="ai-note">읽기 전용 · 숫자는 도구 조회 결과에서만 인용{role === "controller" ? " · 담당 제대 기록만 조회" : ""}</div>
      <div className="ai-thread">
        {items.length === 0 && <p className="empty">질문을 입력하거나 아래 예시를 눌러 보세요.</p>}
        {items.map((it, i) => (
          <div key={i} className="ai-turn">
            <div className="ai-q">{it.q}</div>
            {it.pending && <div className="ai-a pending">기록을 조회하는 중…</div>}
            {it.error && <div className="ai-a error">{it.error}</div>}
            {it.a && (
              <div className="ai-a">
                <Answer text={it.a.answer} onCite={(id) => setOpenEv((cur) => ({ ...cur, [`${i}:${id}`]: !cur[`${i}:${id}`] }))} />
                {it.a.warnings.length > 0 && (
                  <ul className="ai-warn">{it.a.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
                )}
                {it.a.warnings.length === 0 && it.a.evidences.length > 0 && <div className="ai-ok">숫자·인용 확인 통과</div>}
                {it.a.evidences.map((ev) => <Evidence key={ev.id} ev={ev} open={!!openEv[`${i}:${ev.id}`]} />)}
              </div>
            )}
          </div>
        ))}
        <div ref={endRef} />
      </div>
      <div className="ai-sugg">
        {(SUGGESTIONS[role === "commander" ? "commander" : "operator"]).map((s) => <button key={s} onClick={() => send(s)}>{s}</button>)}
      </div>
      <form className="ai-ask" onSubmit={(e) => { e.preventDefault(); send(text); }}>
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder="질문을 입력하세요" maxLength={500} aria-label="질문" />
        <button aria-label="보내기" disabled={!text.trim()}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M5 12h14" /><path d="M13 6l6 6-6 6" /></svg>
        </button>
      </form>
    </div>
  );
}
