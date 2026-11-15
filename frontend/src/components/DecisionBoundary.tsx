import type { ModelsData } from "../lib/types";
import { fmtNum } from "../lib/format";
import { MODEL_ROLES, MODEL_SHORT, modelFamily } from "../lib/science";
import { Badge } from "./ui";

export function DecisionBoundary({ models }: { models: ModelsData }) {
  const operational = models.available.filter((model) => modelFamily(model) === "operational");
  const research = models.available.filter((model) => modelFamily(model) === "research");
  const winner = models.selection.winner;
  const served = models.served;

  return (
    <div>
      <div className="decision-grid">
        <div className="decision-zone safe">
          <div className="flex items-center justify-between gap-2 mb-2">
            <div>
              <div className="eyebrow" style={{ color: "#526B5B" }}>
                Safe zone · operational path
              </div>
              <div className="text-[12px] muted mt-1">
                Physics-structured, audited, and allowed to return a served correction.
              </div>
            </div>
            <Badge tone="ok">selectable</Badge>
          </div>
          <div className="stack" style={{ gap: 6 }}>
            {operational.map((model) => (
              <div key={model} className={`model-card${model === served ? " active" : ""}`}>
                <div className="flex items-center gap-2 min-w-0">
                  <span className="model-id">{model}</span>
                  <div className="min-w-0">
                    <div className="text-[11.5px] font-semibold truncate">{MODEL_SHORT[model]}</div>
                    <div className="text-[9.5px] muted truncate">{MODEL_ROLES[model]}</div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className="mono text-[10px]">{fmtNum(models.grouped_cv[model]?.rmse, 4)}</span>
                  {model === served ? <Badge tone="ok">served</Badge> : <Badge tone="plain">baseline</Badge>}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="decision-boundary" aria-label="Governance boundary">
          <div className="boundary-line" />
          <div className="boundary-label">owner sign-off</div>
          <div className="boundary-line" />
        </div>

        <div className="decision-zone research">
          <div className="flex items-center justify-between gap-2 mb-2">
            <div>
              <div className="eyebrow" style={{ color: "#5B6E74" }}>
                Research zone · not switchable
              </div>
              <div className="text-[12px] muted mt-1">
                Lower measured error does not grant operational authority.
              </div>
            </div>
            <Badge tone="info">research only</Badge>
          </div>
          <div className="stack" style={{ gap: 6 }}>
            {research.map((model) => (
              <div key={model} className="model-card research">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="model-id">{model}</span>
                  <div className="min-w-0">
                    <div className="text-[11.5px] font-semibold truncate">{MODEL_SHORT[model]}</div>
                    <div className="text-[9.5px] muted truncate">{MODEL_ROLES[model]}</div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className="mono text-[10px]">{fmtNum(models.grouped_cv[model]?.rmse, 4)}</span>
                  {model === winner ? <Badge tone="warn">selection winner</Badge> : <Badge tone="none">not served</Badge>}
                </div>
              </div>
            ))}
          </div>
          <div className="callout warn mt-sm">
            <span className="callout-title">The boundary is governance, not accuracy</span>
            {winner !== served ? (
              <>
                The pre-registered selection winner is <b>{winner}</b>; the product still serves{" "}
                <b>{served}</b>. The disagreement is disclosed rather than resolved by quietly
                promoting the lower-RMSE model. Switching requires owner sign-off because the ML
                models learn sampling coverage as well as timing, and they are not
                physics-interpretable at the cell-day boundary.
              </>
            ) : (
              <>The pre-registered selection winner matches the served model.</>
            )}
          </div>
        </div>
      </div>
      <p className="table-note">{models.served_note}</p>
    </div>
  );
}
