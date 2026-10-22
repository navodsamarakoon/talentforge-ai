import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import "./robot-test.css";
const SplineRobot = lazy(() => import("./SplineRobot"));

function measure(element: HTMLElement | null) {
  if (!element) return "0 × 0";
  const { width, height } = element.getBoundingClientRect();
  return `${Math.round(width)} × ${Math.round(height)}`;
}

export default function RobotTestPage() {
  const canvasRef = useRef<HTMLElement>(null);
  const [viewport, setViewport] = useState(() => `${window.innerWidth} × ${window.innerHeight}`);
  const [canvasSize, setCanvasSize] = useState("0 × 0");
  const [loaded, setLoaded] = useState(false);

  const updateMeasurements = useCallback(() => {
    setViewport(`${window.innerWidth} × ${window.innerHeight}`);
    setCanvasSize(measure(canvasRef.current));
  }, []);
  const onSceneStatusChange = useCallback((status: "loading" | "loaded" | "error") => setLoaded(status === "loaded"), []);

  useEffect(() => {
    updateMeasurements();
    window.addEventListener("resize", updateMeasurements);
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(updateMeasurements);
    if (canvasRef.current) observer?.observe(canvasRef.current);
    return () => { window.removeEventListener("resize", updateMeasurements); observer?.disconnect(); };
  }, [updateMeasurements]);

  return <main className="robot-test-page">
    <section className="robot-test-canvas" ref={canvasRef} aria-label="Spline robot scene">
      <Suspense fallback={<div className="robot-test-status" role="status">Loading Spline scene…</div>}>
        <SplineRobot onStatusChange={onSceneStatusChange} />
      </Suspense>
    </section>
    <aside className="robot-test-debug" aria-label="Scene diagnostics">
      <span>Viewport: {viewport}</span><span>Canvas: {canvasSize}</span><span>Scene loaded: {loaded ? "Yes" : "No"}</span>
    </aside>
  </main>;
}
