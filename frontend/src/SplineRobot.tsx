import { Component, useEffect, useState, type ErrorInfo, type ReactNode } from "react";
import Spline from "@splinetool/react-spline";
import "./spline-robot.css";

const SCENE_URL = "https://prod.spline.design/0F4Z9rX1AsFWaYh7/scene.splinecode";
const LOAD_TIMEOUT_MS = 30_000;

type BoundaryProps = { children: ReactNode; onError: (error: Error) => void };
type BoundaryState = { error: Error | null };

class SceneErrorBoundary extends Component<BoundaryProps, BoundaryState> {
  state: BoundaryState = { error: null };
  static getDerivedStateFromError(error: Error): BoundaryState { return { error }; }
  componentDidCatch(error: Error, _info: ErrorInfo) { this.props.onError(error); }
  render() { return this.state.error ? null : this.props.children; }
}

export type SplineRobotStatus = "loading" | "loaded" | "error";

export default function SplineRobot({ onStatusChange }: { onStatusChange?: (status: SplineRobotStatus) => void }) {
  const [attempt, setAttempt] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    if (loaded || error) return;
    const timeout = window.setTimeout(() => setError(new Error("The Spline scene did not finish loading within 30 seconds.")), LOAD_TIMEOUT_MS);
    return () => window.clearTimeout(timeout);
  }, [attempt, error, loaded]);

  useEffect(() => { onStatusChange?.(error ? "error" : loaded ? "loaded" : "loading"); }, [error, loaded, onStatusChange]);

  const retry = () => { setError(null); setLoaded(false); setAttempt(value => value + 1); };
  const fail = (caught: Error) => setError(caught);

  return <div className="spline-robot">
    {error ? <div className="spline-robot-message" role="alert">
      <p>Spline could not load this scene. Check the browser console and network request, then retry.</p>
      <button type="button" onClick={retry}>Retry scene</button>
    </div> : <>
      {!loaded && <div className="spline-robot-loading" role="status"><span className="spline-robot-spinner" />Loading robot…</div>}
      <SceneErrorBoundary key={attempt} onError={fail}>
        <Spline scene={SCENE_URL} onLoad={() => setLoaded(true)} />
      </SceneErrorBoundary>
    </>}
  </div>;
}
