import { useAppData } from "../context/AppData";
import { ErrorPage, LoadingPage } from "../components/States";
import { DecisionBoundary } from "../components/DecisionBoundary";
import { ModelRmseChart } from "../components/charts";
import {
  Badge,
  Callout,
  Limitations,
  Metric,
  MetricStrip,
  PageHeader,
  Panel,
} from "../components/ui";
import { fmtInt, fmtNum, fmtSigned, humanRegion } from "../lib/format";
import { MODEL_ROLES, MODEL_SHORT, modelFamily } from "../lib/science";

export function Models() {
  const { results, loading, error } = useAppData();
  if (loading && !results) return <LoadingPage />;
  if (error || !results) return <ErrorPage message={error} />;

  const models = results.models;
  const grouped = models.grouped_cv;
  const sortedGrouped = [...models.available].sort((a, b) => grouped[a].rmse - grouped[b].rmse);
  const lowest = sortedGrouped[0];
  const selectionSorted = Object.entries(models.selection.mean_rmse).sort(([, a], [, b]) => a - b);
  const foldYears = models.selection.years.map(String);

  return (
    <div>
      <PageHeader
        kicker="Compare without declaring an unsupported winner"
        title="Model comparison"
        lede={
          <>
            Lower grouped-CV RMSE means lower prediction error in log-ratio units. H is the served
            physics-structured model; M and PR are research comparisons. The selection evidence is
            shown even when it disagrees with the serving decision.
          </>
        }
        side={
          <>
            <Badge tone="ok">{models.served} served</Badge>
            <span className="mono tiny muted">{models.available.length} models evaluated</span>
          </>
        }
      />

      <MetricStrip>
        <Metric
          label="Served model"
          badge={<Badge tone="ok" symbol={<span aria-hidden>◆</span>}>{models.served}</Badge>}
          value={MODEL_ROLES[models.served] ?? models.served}
          small
          hint="conformal 80% intervals · operational path"
        />
        <Metric
          label="Selection winner"
          value={models.selection.winner}
          small
          hint={`mean RMSE across folds ${models.selection.years.join(" + ")}`}
        />
        <Metric
          label={`${models.served} grouped RMSE`}
          value={fmtNum(grouped[models.served]?.rmse, 4)}
          hint={`bias ${fmtSigned(grouped[models.served]?.bias, 4)} ln`}
        />
        <Metric
          label={`Lowest (${lowest})`}
          value={fmtNum(grouped[lowest]?.rmse, 4)}
          hint="research model · not operationally selectable"
        />
        <Metric
          label="Pairs scored"
          value={fmtInt(grouped[models.served]?.n)}
          hint="grouped CV · fold = whole 5-day window"
        />
      </MetricStrip>

      <div className="grid side mt">
        <Panel
          title="Grouped cross-validation RMSE"
          meta="fold = whole 5-day sampling window · axis starts above zero to resolve differences"
        >
          <ModelRmseChart grouped={grouped} served={models.served} family={modelFamily} />
          <div className="chart-legend">
            <span>
              <i className="swatch" style={{ background: "#3B5345" }} />
              served H
            </span>
            <span>
              <i className="swatch" style={{ background: "#8FA793" }} />
              physics / baseline family
            </span>
            <span>
              <i className="swatch" style={{ background: "#788B91" }} />
              statistical ML / research
            </span>
          </div>
          <p className="table-note">
            RMSE around 1.0 ln is the cell-day noise floor. A lower RMSE is not evidence that a model
            removes timing bias; it may be learning sampling coverage instead.
          </p>
        </Panel>

        <Panel title="Pre-registered selection" meta={`mean RMSE · folds ${models.selection.years.join(", ")}`}>
          <div className="stack" style={{ gap: 7 }}>
            {selectionSorted.map(([model, value]) => (
              <div key={model} className={`model-card${model === models.selection.winner ? " active" : ""}`}>
                <div className="flex items-center gap-2">
                  <span className="model-id">{model}</span>
                  <span className="text-[10.5px] muted">{MODEL_SHORT[model]}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="mono text-[10px]">{fmtNum(value, 4)}</span>
                  {model === models.selection.winner && <Badge tone="warn">winner</Badge>}
                  {model === models.served && <Badge tone="ok">served</Badge>}
                </div>
              </div>
            ))}
          </div>
          <Callout
            tone={models.selection.winner !== models.served ? "warn" : "good"}
            title={
              models.selection.winner !== models.served
                ? "Selection and serving disagree"
                : "Selection matches serving"
            }
            className="mt-sm"
          >
            {models.selection.winner !== models.served ? (
              <>
                The pre-registered fold-mean winner is <b>{models.selection.winner}</b>, but the
                product serves <b>{models.served}</b>. The evidence is shown rather than hidden; a
                switch requires owner sign-off.
              </>
            ) : (
              <>The winner matches the served model.</>
            )}
          </Callout>
          {foldYears.length > 0 && (
            <div className="table-wrap mt-sm">
              <table className="data">
                <thead>
                  <tr>
                    <th>Fold</th>
                    <th className="num">n train</th>
                    <th className="num">n test</th>
                    <th className="num">H RMSE</th>
                    <th className="num">M RMSE</th>
                  </tr>
                </thead>
                <tbody>
                  {foldYears.map((year) => {
                    const fold = models.selection.folds[year];
                    const h = fold?.H;
                    const m = fold?.M;
                    return (
                      <tr key={year}>
                        <td className="mono">{year}</td>
                        <td className="num">{fmtInt(fold?.n_train)}</td>
                        <td className="num">{fmtInt(fold?.n_test)}</td>
                        <td className="num">
                          {typeof h === "object" && h !== null ? fmtNum(h.rmse, 4) : "—"}
                        </td>
                        <td className="num">
                          {typeof m === "object" && m !== null ? fmtNum(m.rmse, 4) : "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </div>

      <Panel className="mt" title="Model scorecard" meta={`measured on ${fmtInt(grouped[models.served]?.n)} Aqua–SNPP pairs`}>
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Model</th>
                <th>Role</th>
                <th>Family</th>
                <th className="num">RMSE (ln)</th>
                <th className="num">Bias (ln)</th>
                <th className="num">MAE (ln)</th>
                <th className="num">n</th>
                <th>Serving</th>
              </tr>
            </thead>
            <tbody>
              {models.available.map((model) => {
                const metric = grouped[model];
                const family = modelFamily(model);
                return (
                  <tr key={model}>
                    <td className="mono strong">{model}</td>
                    <td>{MODEL_ROLES[model] ?? model}</td>
                    <td>
                      <Badge tone={family === "research" ? "info" : "ok"}>
                        {family === "research" ? "research ML" : "physics / baseline"}
                      </Badge>
                    </td>
                    <td className="num">{fmtNum(metric?.rmse, 5)}</td>
                    <td className="num">{fmtSigned(metric?.bias, 5)}</td>
                    <td className="num">{fmtNum(metric?.mae, 5)}</td>
                    <td className="num">{fmtInt(metric?.n)}</td>
                    <td>
                      {model === models.served ? (
                        <Badge tone="ok">served</Badge>
                      ) : family === "research" ? (
                        <Badge tone="none">not switchable</Badge>
                      ) : (
                        <Badge tone="plain">baseline</Badge>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="table-note">
          Bias is the mean log-ratio residual; a value near zero means the average scale matches, not
          that individual predictions are accurate. The lowest RMSE belongs to a research model, and
          that fact is reported rather than used to promote it.
        </p>
      </Panel>

      <Panel className="mt" title="Decision boundary & safe zone" meta="accuracy does not grant operational authority">
        <DecisionBoundary models={models} />
      </Panel>

      <Panel className="mt" title="Regional transfer" meta="leave-one-region-out · H vs P vs raw baseline">
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Region</th>
                <th className="num">n</th>
                <th className="num">B0 raw RMSE</th>
                <th className="num">P RMSE</th>
                <th className="num">H RMSE</th>
                <th>Reading</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(models.loyo).map(([region, entry]) => {
                const worse = entry.H.rmse > entry.B0.rmse;
                return (
                  <tr key={region}>
                    <td>{humanRegion(region)}</td>
                    <td className="num">{fmtInt(entry.n)}</td>
                    <td className="num">{fmtNum(entry.B0.rmse, 4)}</td>
                    <td className="num">{fmtNum(entry.P.rmse, 4)}</td>
                    <td className="num">{fmtNum(entry.H.rmse, 4)}</td>
                    <td>
                      {worse ? (
                        <Badge tone="warn">H worse than raw</Badge>
                      ) : (
                        <Badge tone="ok">H improves on raw</Badge>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="table-note">
          A regional RMSE is a validation score for that region, not the uncertainty of an individual
          prediction. Missing regional results are not invented. Amazon is the clearest negative
          result: the correction is worse than doing nothing.
        </p>
      </Panel>

      <Limitations items={results.limitations} />
    </div>
  );
}
