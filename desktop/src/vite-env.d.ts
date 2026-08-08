/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 仅开发时使用：手动启动后端后填入，可在浏览器里直接调界面 */
  readonly VITE_BACKEND_HTTP?: string;
  readonly VITE_BACKEND_TOKEN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
