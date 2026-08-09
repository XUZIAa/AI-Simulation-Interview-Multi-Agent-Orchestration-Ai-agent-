import { useEffect, useRef } from "react";

/** 面试官说话时的声波光球。
 *
 *  电平每 100ms 一更新，走 React 状态会引发大量重渲染，所以直接画在 canvas 上，
 *  外部通过 ref 推数值进来，完全不经过 React 的更新流程。 */
export interface OrbHandle {
  setLevel: (level: number) => void;
  setActive: (active: boolean) => void;
}

export function VoiceOrb({
  handleRef,
  size = 160,
  color = "var(--interviewer)",
}: {
  handleRef: React.RefObject<OrbHandle | null>;
  size?: number;
  color?: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    canvas.width = size * dpr;
    canvas.height = size * dpr;
    ctx.scale(dpr, dpr);

    const accent = getComputedStyle(canvas).getPropertyValue("color") || "#5b5bd6";
    let level = 0;
    let smooth = 0;
    let active = false;
    let phase = 0;
    let raf = 0;

    handleRef.current = {
      setLevel: (v) => {
        level = Math.max(0, Math.min(1, v));
      },
      setActive: (v) => {
        active = v;
      },
    };

    const draw = () => {
      // 平滑跟随：直接用瞬时电平会抖得厉害
      smooth += (level - smooth) * 0.18;
      phase += active ? 0.05 : 0.015;

      const c = size / 2;
      const base = size * 0.26;
      ctx.clearRect(0, 0, size, size);

      // 外层呼吸圈，随音量扩张
      for (let i = 3; i >= 1; i--) {
        const spread = base + i * size * 0.045 + smooth * size * 0.1;
        ctx.beginPath();
        ctx.arc(c, c, spread, 0, Math.PI * 2);
        ctx.fillStyle = accent;
        ctx.globalAlpha = (active ? 0.09 : 0.04) / i + smooth * 0.05;
        ctx.fill();
      }

      // 主球，轻微起伏让静默时也不是死的
      const wobble = Math.sin(phase) * size * 0.012;
      ctx.beginPath();
      ctx.arc(c, c, base + smooth * size * 0.06 + wobble, 0, Math.PI * 2);
      const grad = ctx.createRadialGradient(c - base * 0.3, c - base * 0.35, base * 0.15, c, c, base * 1.2);
      grad.addColorStop(0, accent);
      grad.addColorStop(1, accent);
      ctx.fillStyle = grad;
      ctx.globalAlpha = active ? 1 : 0.55;
      ctx.fill();

      ctx.globalAlpha = 1;
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);

    return () => {
      cancelAnimationFrame(raf);
      handleRef.current = null;
    };
  }, [handleRef, size]);

  return (
    <canvas
      ref={canvasRef}
      style={{ width: size, height: size, color }}
      aria-hidden
    />
  );
}

/** 候选人音量条。同样走 canvas，理由与光球一致。 */
export interface MeterHandle {
  setLevel: (level: number) => void;
}

export function LevelMeter({
  handleRef,
  bars = 24,
  height = 28,
}: {
  handleRef: React.RefObject<MeterHandle | null>;
  bars?: number;
  height?: number;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const parent = canvas.parentElement;
    const width = parent?.clientWidth || 240;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    ctx.scale(dpr, dpr);

    const accent = getComputedStyle(canvas).getPropertyValue("color") || "#0f8a5f";
    const history = new Array<number>(bars).fill(0);
    let level = 0;
    let raf = 0;
    let tick = 0;

    handleRef.current = {
      setLevel: (v) => {
        level = Math.max(0, Math.min(1, v));
      },
    };

    const draw = () => {
      // 每三帧推进一格，否则波形滚动过快看不清
      if (tick++ % 3 === 0) {
        history.push(level);
        history.shift();
      }
      ctx.clearRect(0, 0, width, height);
      const gap = 2;
      const barWidth = (width - gap * (bars - 1)) / bars;
      for (let i = 0; i < bars; i++) {
        const v = history[i];
        const h = Math.max(2, v * height);
        ctx.fillStyle = accent;
        ctx.globalAlpha = 0.25 + v * 0.75;
        ctx.beginPath();
        ctx.roundRect(i * (barWidth + gap), (height - h) / 2, barWidth, h, barWidth / 2);
        ctx.fill();
      }
      ctx.globalAlpha = 1;
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);

    return () => {
      cancelAnimationFrame(raf);
      handleRef.current = null;
    };
  }, [handleRef, bars, height]);

  return (
    <div className="w-full">
      <canvas ref={canvasRef} style={{ width: "100%", height, color: "var(--candidate)" }} aria-hidden />
    </div>
  );
}
