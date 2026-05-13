const listeners = new Set();

export const state = {
  activeModule: "shunshou",
  logs: [],
  activeTasks: [],
};

export function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function setActiveModule(moduleId) {
  state.activeModule = moduleId;
  emit();
}

export function addLog(level, message, context = "") {
  const now = new Date();
  state.logs.push({
    timestamp: now.getTime(),
    time: now.toLocaleTimeString("zh-CN", { hour12: false }),
    level,
    message,
    context,
  });
  state.logs = state.logs.slice(-100);
  emit();
}

export function startTask(message, context = "") {
  const id = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  state.activeTasks.push({ id, message, context, startedAt: Date.now() });
  emit();
  return id;
}

export function endTask(id) {
  state.activeTasks = state.activeTasks.filter((task) => task.id !== id);
  emit();
}

function emit() {
  listeners.forEach((listener) => listener(state));
}
