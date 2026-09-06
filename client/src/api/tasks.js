import { authRequest, taggedRequest, unwrapEnvelope } from "./_core.js";
import { ROUTES } from "./_routes.js";

// `/apps/tasks/list` nests the array one level deeper than the other list routes:
// unwrapping the envelope yields `{tasks: [...], execution_envelope: {...}}`, not an
// array. TaskDashboard does `Array.isArray(data) ? [...data] : []`, so before this
// second unwrap every task list rendered as "No active directives" — a created task
// persisted fine and simply never appeared.
export const getTasks = taggedRequest("tasks", () =>
  authRequest(ROUTES.TASKS.LIST, { method: "GET" })
    .then(unwrapEnvelope)
    .then((data) => (Array.isArray(data) ? data : data?.tasks ?? []))
);

export const createTask = taggedRequest("tasks", (taskData) =>
  authRequest(ROUTES.TASKS.CREATE, {
    method: "POST",
    body: JSON.stringify(taskData),
  }).then(unwrapEnvelope)
);

export const completeTask = taggedRequest("tasks", (taskName) =>
  authRequest(ROUTES.TASKS.COMPLETE, {
    method: "POST",
    body: JSON.stringify({ name: taskName }),
  }).then(unwrapEnvelope)
);

// The delete capability existed as a syscall (`sys.v1.task.delete_by_ids`) with no HTTP
// route and no UI, so a task created by mistake could only be removed from the database by
// hand. The route was added alongside this.
export const deleteTask = taggedRequest("tasks", (taskName) =>
  authRequest(ROUTES.TASKS.DELETE, {
    method: "POST",
    body: JSON.stringify({ name: taskName }),
  }).then(unwrapEnvelope)
);

export const startTask = taggedRequest("tasks", (taskName) =>
  authRequest(ROUTES.TASKS.START, {
    method: "POST",
    body: JSON.stringify({ name: taskName }),
  }).then(unwrapEnvelope)
);
