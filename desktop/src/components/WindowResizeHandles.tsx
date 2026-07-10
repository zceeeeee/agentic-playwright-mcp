import { useWindowResize, type ResizeEdge } from "../hooks/useWindowResize";

const edges: ResizeEdge[] = ["n", "ne", "e", "se", "s", "sw", "w", "nw"];

export function WindowResizeHandles() {
  const bindResize = useWindowResize();
  return (
    <div className="window-resize-handles" aria-hidden="true">
      {edges.map((edge) => (
        <span
          className={`window-resize-handle resize-${edge}`}
          key={edge}
          {...bindResize(edge)}
        />
      ))}
    </div>
  );
}
