import { useRef } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";

export type ResizeEdge = "n" | "ne" | "e" | "se" | "s" | "sw" | "w" | "nw";

interface ResizeState {
  edge: ResizeEdge;
  pointerId: number;
  lastX: number;
  lastY: number;
}

export function useWindowResize() {
  const resizeRef = useRef<ResizeState | null>(null);
  const pendingDeltaRef = useRef({ x: 0, y: 0 });
  const animationFrameRef = useRef<number | null>(null);

  function flush(persist: boolean) {
    if (animationFrameRef.current !== null) {
      window.cancelAnimationFrame(animationFrameRef.current);
      animationFrameRef.current = null;
    }
    const state = resizeRef.current;
    const delta = pendingDeltaRef.current;
    pendingDeltaRef.current = { x: 0, y: 0 };
    if (state && (delta.x || delta.y || persist)) {
      void window.desktopAgent.resizeExpandedChat(state.edge, delta.x, delta.y, persist);
    }
  }

  function schedule(dx: number, dy: number) {
    pendingDeltaRef.current.x += dx;
    pendingDeltaRef.current.y += dy;
    if (animationFrameRef.current !== null) return;
    animationFrameRef.current = window.requestAnimationFrame(() => {
      animationFrameRef.current = null;
      flush(false);
    });
  }

  function onPointerDown(edge: ResizeEdge, event: ReactPointerEvent<HTMLSpanElement>) {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    resizeRef.current = {
      edge,
      pointerId: event.pointerId,
      lastX: event.screenX,
      lastY: event.screenY
    };
  }

  function onPointerMove(event: ReactPointerEvent<HTMLSpanElement>) {
    const state = resizeRef.current;
    if (!state || state.pointerId !== event.pointerId) return;
    event.preventDefault();
    event.stopPropagation();
    const dx = event.screenX - state.lastX;
    const dy = event.screenY - state.lastY;
    state.lastX = event.screenX;
    state.lastY = event.screenY;
    if (dx || dy) schedule(dx, dy);
  }

  function finish(event: ReactPointerEvent<HTMLSpanElement>) {
    const state = resizeRef.current;
    if (!state || state.pointerId !== event.pointerId) return;
    flush(true);
    resizeRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }

  return (edge: ResizeEdge) => ({
    onPointerDown: (event: ReactPointerEvent<HTMLSpanElement>) => onPointerDown(edge, event),
    onPointerMove,
    onPointerUp: finish,
    onPointerCancel: finish
  });
}
