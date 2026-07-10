import { useRef } from "react";
import { useAgentStore } from "../stores/agentStore";

const stateLabels = {
  idle: "空闲",
  running: "正在执行",
  waiting_confirmation: "等待确认",
  success: "已完成",
  error: "执行失败"
};

export function PetCircle() {
  const visualState = useAgentStore((state) => state.visualState);
  const pointer = useRef<{
    x: number;
    y: number;
    windowX: number;
    windowY: number;
    dragging: boolean;
  } | null>(null);

  async function onPointerDown(event: React.PointerEvent<HTMLButtonElement>) {
    if (event.button !== 0) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    const bounds = await window.desktopAgent.getWindowBounds();
    pointer.current = {
      x: event.screenX,
      y: event.screenY,
      windowX: bounds.x,
      windowY: bounds.y,
      dragging: false
    };
  }

  function onPointerMove(event: React.PointerEvent<HTMLButtonElement>) {
    const start = pointer.current;
    if (!start) return;
    const dx = event.screenX - start.x;
    const dy = event.screenY - start.y;
    if (!start.dragging && Math.hypot(dx, dy) >= 5) start.dragging = true;
    if (start.dragging) {
      void window.desktopAgent.setPetPosition(start.windowX + dx, start.windowY + dy);
    }
  }

  function onPointerUp(event: React.PointerEvent<HTMLButtonElement>) {
    const start = pointer.current;
    pointer.current = null;
    event.currentTarget.releasePointerCapture(event.pointerId);
    if (start && !start.dragging) void window.desktopAgent.expandChat();
  }

  return (
    <button
      className={`pet-circle state-${visualState}`}
      aria-label={`桌面智能体，${stateLabels[visualState]}`}
      title={stateLabels[visualState]}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onContextMenu={(event) => {
        event.preventDefault();
        void window.desktopAgent.showPetMenu();
      }}
    >
      <span className="pet-core" />
      <span className="pet-ring" />
    </button>
  );
}
