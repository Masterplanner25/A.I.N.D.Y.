// What to ask the agent (owner, 2026-11-11): jobs its tools do well, the first about the person's top goal.
// Each `uses` names real agent tools; agent-starting-points.test.jsx checks them.

export function startingPoints(topGoal) {
  const goal = topGoal ? `my goal "${topGoal}"` : "what my plan says matters most right now";
  return [
    {
      title: "Turn a goal into this week's work",
      why: "Reads where you are and what you've done, then writes tasks you can finish.",
      uses: "reasoning.evaluate · memory.recall · task.create",
      objective: `Look at my current state and what I've worked on recently. For ${goal}, create the three most useful `
        + "next tasks, each something I can finish in a day.",
    },
    {
      title: "Research that stays",
      why: "Saved to your memory, so later drafts, recalls and plans use it.",
      uses: "research.query · memory.write",
      objective: "Research [topic], then save the findings to my memory tagged [tag].",
    },
    {
      title: "Draft from your own writing",
      why: "Starts from what you've published, and knows your Works and what search engines get wrong about you.",
      uses: "memory.recall · content.draft",
      objective: "Recall what I've written about [subject] and draft an outline for a piece on it for [audience].",
    },
    {
      title: "Record your market as you see it",
      why: "Each finding waits for you to confirm it under Market.",
      uses: "market.propose",
      objective: "Record [name] as [a competitor | a channel where my buyers gather] in my market, for me to confirm.",
    },
    {
      title: "Review a code file",
      why: "Architecture and integrity scores with a summary, for one file.",
      uses: "arm.analyze",
      objective: "Analyze the file [path/to/file.py].",
    },
  ];
}
