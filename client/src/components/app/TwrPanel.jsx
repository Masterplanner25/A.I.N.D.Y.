import { useState } from "react";
import { calculateTwr } from "../../api/analytics.js";

// Time-to-Wealth Ratio — a what-if calculator (formerly the "Core Metrics" tab of the platform
// Execution Console). Manual input only; nothing is read from or written to your account.
export default function TwrPanel() {
  const [taskName, setTaskName] = useState("");
  const [timeSpent, setTimeSpent] = useState(1);
  const [complexity, setComplexity] = useState(3);
  const [skill, setSkill] = useState(3);
  const [aiUse, setAiUse] = useState(3);
  const [difficulty, setDifficulty] = useState(3);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const panelStyle = { backgroundColor: "#141414", padding: "15px", borderRadius: "8px", border: "1px solid #222", marginBottom: "15px" };
  const inputStyle = { backgroundColor: "#222", color: "#fff", border: "1px solid #444", padding: "10px", borderRadius: "4px", width: "100%", boxSizing: "border-box" };
  const labelStyle = { fontSize: "11px", color: "#888" };

  const handleSubmit = async () => {
    setError(null);
    try {
      const data = await calculateTwr({
        task_name: taskName,
        time_spent: parseFloat(timeSpent),
        task_complexity: parseInt(complexity),
        skill_level: parseInt(skill),
        ai_utilization: parseInt(aiUse),
        task_difficulty: parseInt(difficulty),
      });
      setResult(data);
    } catch (err) {
      setError(err?.message || "TWR calculation failed.");
    }
  };

  return (
    <div style={panelStyle}>
      <h3 style={{ marginTop: 0, fontSize: "16px", color: "#64b5f6" }}>Time-to-Wealth Ratio</h3>
      <div style={{ marginBottom: "10px" }}>
        <label style={labelStyle}>Task name</label>
        <input style={inputStyle} value={taskName} onChange={(e) => setTaskName(e.target.value)} />
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px", marginBottom: "10px" }}>
        <div><label style={labelStyle}>Time (hrs)</label><input style={inputStyle} type="number" value={timeSpent} onChange={(e) => setTimeSpent(e.target.value)} /></div>
        <div><label style={labelStyle}>Complexity (1-5)</label><input style={inputStyle} type="number" value={complexity} onChange={(e) => setComplexity(e.target.value)} /></div>
        <div><label style={labelStyle}>Skill (1-5)</label><input style={inputStyle} type="number" value={skill} onChange={(e) => setSkill(e.target.value)} /></div>
        <div><label style={labelStyle}>AI use (1-5)</label><input style={inputStyle} type="number" value={aiUse} onChange={(e) => setAiUse(e.target.value)} /></div>
        <div><label style={labelStyle}>Difficulty (1-5)</label><input style={inputStyle} type="number" value={difficulty} onChange={(e) => setDifficulty(e.target.value)} /></div>
      </div>
      <button style={{ backgroundColor: "#64b5f6", color: "#000", border: "none", padding: "10px", borderRadius: "6px", cursor: "pointer", width: "100%", fontWeight: "bold" }} onClick={handleSubmit}>
        Calculate TWR
      </button>
      {error && <div style={{ marginTop: "10px", color: "#ff4d4d", fontSize: "12px" }}>{error}</div>}
      {result && (
        <pre style={{ marginTop: "10px", padding: "10px", background: "#000", color: "#64b5f6", fontSize: "12px", borderRadius: "4px", border: "1px solid #333", whiteSpace: "pre-wrap" }}>
          {JSON.stringify(result, null, 2)}
        </pre>
      )}
    </div>
  );
}
