// Thin fetch wrappers. Every call throws an Error with the server's `detail` message.

export class ApiError extends Error {
  constructor(message, status, body) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

async function request(method, url, body, { form = false, signal } = {}) {
  const opts = { method, signal, headers: {} };
  if (body !== undefined) {
    if (form) {
      opts.body = body;
    } else {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
  }
  let res;
  try {
    res = await fetch(url, opts);
  } catch (err) {
    if (err.name === "AbortError") throw err;
    throw new ApiError("Can't reach the Xcelord server. Is it still running?", 0);
  }
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { detail: text }; }
  if (!res.ok) {
    const detail = data?.detail;
    const message = typeof detail === "string" ? detail
      : Array.isArray(detail) ? detail.map((d) => d.msg).join("; ")
      : `Request failed (${res.status})`;
    throw new ApiError(message, res.status, data);
  }
  return data;
}

export const api = {
  meta: () => request("GET", "/api/meta"),
  settings: () => request("GET", "/api/settings"),
  saveSettings: (patch) => request("PUT", "/api/settings", patch),
  testProvider: (provider, key) => request("POST", `/api/providers/${provider}/test`, { key }),

  transcribe: (wavBlob, signal) => {
    const fd = new FormData();
    fd.append("audio", wavBlob, "command.wav");
    return request("POST", "/api/transcribe", fd, { form: true, signal });
  },
  command: (text, signal) => request("POST", "/api/command", { text }, { signal }),
  accept: (id) => request("POST", `/api/proposals/${id}/accept`),
  reject: (id) => request("POST", `/api/proposals/${id}/reject`),

  workbook: () => request("GET", "/api/workbook"),
  openSample: () => request("POST", "/api/workbook/sample"),
  openPath: (path) => request("POST", "/api/workbook/open", { path }),
  upload: (file) => {
    const fd = new FormData();
    fd.append("file", file, file.name);
    return request("POST", "/api/workbook/upload", fd, { form: true });
  },
  setActive: (sheet) => request("PUT", "/api/workbook/active", { sheet }),
  editCell: (sheet, row, col, value) => request("POST", "/api/workbook/cell", { sheet, row, col, value }),
  undo: () => request("POST", "/api/workbook/undo"),
  redo: () => request("POST", "/api/workbook/redo"),
};
