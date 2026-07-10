import { useRef } from "react";

interface DragState {
  pointerId: number;
  startX: number;
  startY: number;
  windowX: number;
  windowY: number;
  dragging: boolean;
}

export function useWindowDrag(enabled = true) {
  const drag = useRef<DragState | null>(null);

  async function onPointerDown(event: React.PointerEvent<HTMLElement>) {
    if (!enabled || event.button !== 0) return;
    const target = event.target as HTMLElement;
    if (target.closest("button,input,textarea,select,a,[data-no-drag]")) return;
    const header = event.currentTarget;
    header.setPointerCapture(event.pointerId);
    const startX = event.screenX;
    const startY = event.screenY;
    const bounds = await window.desktopAgent.getWindowBounds();
    if (!header.hasPointerCapture(event.pointerId)) return;
    drag.current = {
      pointerId: event.pointerId,
      startX,
      startY,
      windowX: bounds.x,
      windowY: bounds.y,
      dragging: false
    };
  }

  function onPointerMove(event: React.PointerEvent<HTMLElement>) {
    const state = drag.current;
    if (!state || state.pointerId !== event.pointerId) return;
    const dx = event.screenX - state.startX;
    const dy = event.screenY - state.startY;
    if (!state.dragging && Math.hypot(dx, dy) >= 5) state.dragging = true;
    if (state.dragging) {
      void window.desktopAgent.setWindowPosition(state.windowX + dx, state.windowY + dy);
    }
  }

  function finishDrag(event: React.PointerEvent<HTMLElement>) {
    if (drag.current?.pointerId !== event.pointerId) return;
    drag.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }

  return {
    onPointerDown,
    onPointerMove,
    onPointerUp: finishDrag,
    onPointerCancel: finishDrag
  };
}
