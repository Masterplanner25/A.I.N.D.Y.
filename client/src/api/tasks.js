import { authRequest, taggedRequest } from "./_core.js";
import { ROUTES } from "./_routes.js";

// `/apps/tasks/list` nests the array one level deeper than the other list routes:
// the resolved envelope (ui-kit resolves it in `request()`) is `{tasks: [...], execution_envelope: {...}}`, not an
// array. TaskDashboard does `Array.isArray(data) ? [...data] : []`, so before this
// second unwrap every task list rendered as "No active directives" — a created task
// persisted fine and simply never appeared.
export const getTasks = taggedRequest("tasks", () =>
  authRequest(ROUTES.TASKS.LIST, { method: "GET" })
    .then((data) => (Array.isArray(data) ? data : data?.tasks ?? []))
);

export const createTask = taggedRequest("tasks", (taskData) =>
  authRequest(ROUTES.TASKS.CREATE, {
    method: "POST",
    body: JSON.stringify(taskData),
  })
);

// `judgement` carries the 1-5 complexity/difficulty recorded at completion. They feed WCU
// (`effort x complexity x difficulty`) and were permanently 1 until this was collected.
// Optional: a caller that omits them leaves the columns untouched rather than defaulting.
export const completeTask = taggedRequest("tasks", (taskName, judgement = {}) =>
  authRequest(ROUTES.TASKS.COMPLETE, {
    method: "POST",
    body: JSON.stringify({
      name: taskName,
      ...(judgement.complexity ? { task_complexity: judgement.complexity } : {}),
      ...(judgement.difficulty ? { task_difficulty: judgement.difficulty } : {}),
    }),
  })
);

// The delete capability existed as a syscall (`sys.v1.task.delete_by_ids`) with no HTTP
// route and no UI, so a task created by mistake could only be removed from the database by
// hand. The route was added alongside this.
export const deleteTask = taggedRequest("tasks", (taskName) =>
  authRequest(ROUTES.TASKS.DELETE, {
    method: "POST",
    body: JSON.stringify({ name: taskName }),
  })
);

export const startTask = taggedRequest("tasks", (taskName) =>
  authRequest(ROUTES.TASKS.START, {
    method: "POST",
    body: JSON.stringify({ name: taskName }),
  })
);
