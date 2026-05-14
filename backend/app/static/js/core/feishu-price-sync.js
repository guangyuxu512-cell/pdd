import { api } from "../api/client.js";

let runningPromise = null;

export async function runFeishuPriceSync() {
  if (runningPromise) {
    return { skipped: true, reason: "running" };
  }
  runningPromise = api
    .post("/products/skus/prices/sync")
    .then((result) => ({ skipped: false, result }))
    .finally(() => {
      runningPromise = null;
    });
  return runningPromise;
}
