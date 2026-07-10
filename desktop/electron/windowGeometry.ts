export interface WindowRectangle {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface WindowSize {
  width: number;
  height: number;
}

export const DEFAULT_CHAT_SIZE: WindowSize = { width: 400, height: 600 };
export const MIN_CHAT_WIDTH = 340;
export const MIN_CHAT_HEIGHT = 420;

export type ResizeEdge = "n" | "ne" | "e" | "se" | "s" | "sw" | "w" | "nw";

function finiteNumber(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

export function parseChatSize(value: unknown): WindowSize {
  const candidate = value && typeof value === "object"
    ? value as { width?: unknown; height?: unknown }
    : {};
  return {
    width: Math.max(MIN_CHAT_WIDTH, Math.round(finiteNumber(candidate.width, DEFAULT_CHAT_SIZE.width))),
    height: Math.max(MIN_CHAT_HEIGHT, Math.round(finiteNumber(candidate.height, DEFAULT_CHAT_SIZE.height)))
  };
}

export function clampChatBounds(
  requested: WindowRectangle,
  workArea: WindowRectangle
): WindowRectangle {
  const width = Math.min(
    workArea.width,
    Math.max(MIN_CHAT_WIDTH, Math.round(finiteNumber(requested.width, DEFAULT_CHAT_SIZE.width)))
  );
  const height = Math.min(
    workArea.height,
    Math.max(MIN_CHAT_HEIGHT, Math.round(finiteNumber(requested.height, DEFAULT_CHAT_SIZE.height)))
  );
  const requestedX = Math.round(finiteNumber(requested.x, workArea.x));
  const requestedY = Math.round(finiteNumber(requested.y, workArea.y));
  return {
    x: Math.min(Math.max(requestedX, workArea.x), workArea.x + workArea.width - width),
    y: Math.min(Math.max(requestedY, workArea.y), workArea.y + workArea.height - height),
    width,
    height
  };
}

export function resizeChatBoundsBy(
  current: WindowRectangle,
  edge: ResizeEdge,
  deltaX: number,
  deltaY: number,
  workArea: WindowRectangle
): WindowRectangle {
  const dx = Math.round(finiteNumber(deltaX, 0));
  const dy = Math.round(finiteNumber(deltaY, 0));
  const left = edge.includes("w");
  const right = edge.includes("e");
  const top = edge.includes("n");
  const bottom = edge.includes("s");
  let x = current.x;
  let y = current.y;
  let width = current.width;
  let height = current.height;

  if (left) {
    width = Math.max(MIN_CHAT_WIDTH, current.width - dx);
    x = current.x + current.width - width;
  } else if (right) {
    width = Math.max(MIN_CHAT_WIDTH, current.width + dx);
  }
  if (top) {
    height = Math.max(MIN_CHAT_HEIGHT, current.height - dy);
    y = current.y + current.height - height;
  } else if (bottom) {
    height = Math.max(MIN_CHAT_HEIGHT, current.height + dy);
  }
  return clampChatBounds({ x, y, width, height }, workArea);
}
