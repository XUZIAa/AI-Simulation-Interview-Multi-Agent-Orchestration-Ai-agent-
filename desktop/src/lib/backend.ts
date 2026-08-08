import { invoke } from "@tauri-apps/api/core";

export interface BackendInfo {
  http_base: string;
  ws_events: string;
  token: string;
}

/** 后端返回的业务错误。区别于网络故障，这类错误自带给用户看的话术。 */
export class BackendError extends Error {
  readonly kind: string;
  readonly detail: string;
  readonly status: number;

  constructor(status: number, kind: string, userMessage: string, detail = "") {
    super(userMessage);
    this.name = "BackendError";
    this.status = status;
    this.kind = kind;
    this.detail = detail;
  }
}

let info: BackendInfo | null = null;
let starting: Promise<BackendInfo> | null = null;

/** 是否运行在 Tauri 窗口内。浏览器里没有这个注入对象，invoke 不可用。 */
export function inTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

/** 开发时可绕过 Tauri，直连手动启动的后端，改界面不必等 Rust 编译。
 *  只在 dev 模式读取，生产构建里这段配置不生效。 */
function devEndpoint(): BackendInfo | null {
  if (!import.meta.env.DEV) return null;
  const base = import.meta.env.VITE_BACKEND_HTTP;
  const token = import.meta.env.VITE_BACKEND_TOKEN;
  if (!base || !token) return null;
  const ws = base.replace(/^http/, "ws");
  return { http_base: base, ws_events: `${ws}/events?token=${token}`, token };
}

/** 启动（或复用）后端进程。并发调用只会真正拉起一次。 */
export async function ensureBackend(): Promise<BackendInfo> {
  if (info) return info;

  const manual = devEndpoint();
  if (manual) {
    info = manual;
    return info;
  }

  if (!inTauri()) {
    throw new BackendError(
      0,
      "NotInTauri",
      "这个页面需要在桌面应用里打开。直接用浏览器访问拿不到后端的端口与凭据。",
      "若要在浏览器里调试界面，先手动启动后端，再把 VITE_BACKEND_HTTP 与 VITE_BACKEND_TOKEN 写入 desktop/.env.local",
    );
  }

  if (!starting) {
    starting = invoke<BackendInfo>("backend_start")
      .then((res) => {
        info = res;
        return res;
      })
      .finally(() => {
        starting = null;
      });
  }
  return starting;
}

export function backendInfo(): BackendInfo | null {
  return info;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const conn = await ensureBackend();
  const res = await fetch(`${conn.http_base}${path}`, {
    method,
    headers: {
      "X-Interviewer-Token": conn.token,
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (!res.ok) {
    let kind = "HttpError";
    let message = `请求失败（${res.status}）`;
    let detail = "";
    try {
      const payload = await res.json();
      if (typeof payload?.user_message === "string") {
        kind = payload.kind ?? kind;
        message = payload.user_message;
        detail = payload.detail ?? "";
      } else if (typeof payload?.detail === "string") {
        message = payload.detail;
      }
    } catch {
      // 响应体不是 JSON 时保留默认话术
    }
    throw new BackendError(res.status, kind, message, detail);
  }

  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  del: <T>(path: string) => request<T>("DELETE", path),
};

// ==================================================================
// 事件通道
// ==================================================================

export type EventFrame = { event: string; data: Record<string, unknown> };
type Listener = (data: Record<string, unknown>) => void;

const listeners = new Map<string, Set<Listener>>();
let socket: WebSocket | null = null;
let reconnectTimer: number | null = null;
let closedByUs = false;

const connectionListeners = new Set<(connected: boolean) => void>();

function announce(connected: boolean) {
  connectionListeners.forEach((fn) => fn(connected));
}

/** 订阅事件通道的连通状态，用于在界面上如实反映后端是否在线。 */
export function onConnectionChange(fn: (connected: boolean) => void): () => void {
  connectionListeners.add(fn);
  return () => connectionListeners.delete(fn);
}

export function isEventChannelOpen(): boolean {
  return socket?.readyState === WebSocket.OPEN;
}

export async function openEventChannel(): Promise<void> {
  const conn = await ensureBackend();
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
    return;
  }
  closedByUs = false;
  const ws = new WebSocket(conn.ws_events);
  socket = ws;

  ws.onopen = () => announce(true);
  ws.onmessage = (ev) => {
    let frame: EventFrame;
    try {
      frame = JSON.parse(ev.data as string);
    } catch {
      return;
    }
    const pool = listeners.get(frame.event);
    if (!pool) return;
    pool.forEach((fn) => {
      try {
        fn(frame.data);
      } catch (err) {
        console.error(`事件处理出错 ${frame.event}`, err);
      }
    });
  };
  ws.onclose = () => {
    announce(false);
    socket = null;
    if (closedByUs) return;
    // 后端还活着但连接掉了要能自己回来，否则界面会一直停在断线状态
    if (reconnectTimer === null) {
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = null;
        void openEventChannel().catch(() => undefined);
      }, 1200);
    }
  };
  ws.onerror = () => ws.close();
}

export function closeEventChannel(): void {
  closedByUs = true;
  if (reconnectTimer !== null) {
    window.clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  socket?.close();
  socket = null;
}

/** 订阅一类后端事件，返回取消函数。 */
export function onEvent<T = Record<string, unknown>>(
  name: string,
  fn: (data: T) => void,
): () => void {
  let pool = listeners.get(name);
  if (!pool) {
    pool = new Set();
    listeners.set(name, pool);
  }
  const wrapped = fn as Listener;
  pool.add(wrapped);
  return () => {
    pool?.delete(wrapped);
  };
}
