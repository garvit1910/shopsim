"use client";

/** The pipeline stepper. Every step's state is read off real artifacts —
 * uploads staged, ads-manifest written, orchestrator alive, progress ticking,
 * results.json present, comparison.json present — so it can never claim
 * progress the engine has not actually made. */

export type StepState = "done" | "active" | "pending";

export interface Step {
  id: string;
  label: string;
  state: StepState;
  detail?: string;
}

export default function Stepper({ steps }: { steps: Step[] }) {
  return (
    <div className="stepper">
      {steps.map((s, i) => (
        <span key={s.id} style={{ display: "contents" }}>
          {i > 0 && <span className="rule" />}
          <span className={`step ${s.state}`}>
            <i />{s.label}
            {s.detail && <span className="detail">{s.detail}</span>}
          </span>
        </span>
      ))}
    </div>
  );
}

/** Build the six pipeline steps from what the app actually knows. */
export function pipelineSteps(x: {
  hasAds?: boolean;
  perceived?: boolean;
  launched?: boolean;
  runStatus?: string | null;
  tick?: number;
  ticks?: number;
  hasResults?: boolean;
  hasComparison?: boolean;
}): Step[] {
  const running = x.runStatus === "running";
  const complete = x.runStatus === "complete";
  const st = (done: boolean, active = false): StepState =>
    done ? "done" : active ? "active" : "pending";

  return [
    { id: "ingest", label: "INGEST", state: st(Boolean(x.hasAds), false) },
    { id: "perceive", label: "PERCEIVE", state: st(Boolean(x.perceived), Boolean(x.hasAds) && !x.perceived) },
    { id: "launch", label: "LAUNCH", state: st(Boolean(x.launched || running || complete)) },
    {
      id: "simulate", label: "SIMULATE",
      state: complete ? "done" : running ? "active" : "pending",
      detail: running && x.ticks ? `DAY ${(x.tick ?? 0) + 1}/${x.ticks}` : undefined,
    },
    { id: "results", label: "RESULTS", state: st(Boolean(x.hasResults), complete && !x.hasResults) },
    { id: "verdict", label: "VERDICT", state: st(Boolean(x.hasComparison)) },
  ];
}
