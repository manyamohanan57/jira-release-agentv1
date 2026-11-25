"use client";

import { FormEvent, useState } from "react";

type Requirement = {
  requirement_id: string;
  title: string;
  mandatory: boolean;
  decision: "PASS" | "FAIL" | "INSUFFICIENT_EVIDENCE";
  explanation: string;
  evidence: Array<{
    ticket_key: string;
    comment_id?: string;
    source_identifier?: string;
    summary: string;
    applicability: string;
  }>;
  outstanding: string[];
};

type Report = {
  report_id: string;
  project_key: string;
  dataset_label: string;
  target_release: string;
  overall_decision: "READY" | "NEEDS_REVIEW" | "BLOCKED";
  requirements: Requirement[];
  usage: {
    execution_time_ms: number;
    input_tokens?: number;
    output_tokens?: number;
    model_calls: number;
  };
  generated_at: string;
};

const API_URL =
  (process.env.NEXT_PUBLIC_API_BASE_URL ??
    process.env.NEXT_PUBLIC_API_URL ??
    "http://localhost:8000").replace(/\/$/, "");

export default function Home() {
  const [projectKey, setProjectKey] = useState("");
  const [datasetLabel, setDatasetLabel] = useState(
    "tyn-release-assessment-v2",
  );
  const [targetRelease, setTargetRelease] = useState("");
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState("");
  const [running, setRunning] = useState(false);

  async function runAssessment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setRunning(true);
    setError("");
    setReport(null);

    try {
      const response = await fetch(`${API_URL}/assessments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_key: projectKey,
          dataset_label: datasetLabel,
          target_release: targetRelease,
        }),
      });
      if (!response.ok) {
        const body = await response.json();
        throw new Error(body.detail ?? "Assessment failed");
      }
      setReport((await response.json()) as Report);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Assessment failed");
    } finally {
      setRunning(false);
    }
  }

  return (
    <main>
      <header className="header">
        <div>
          <p className="eyebrow">THE YELLOW NETWORK</p>
          <h1>Release Evidence Agent</h1>
        </div>
        <span className="scope">Jira-backed assessment</span>
      </header>

      <section className="controls" aria-label="Assessment inputs">
        <form onSubmit={runAssessment}>
          <label>
            Project key
            <input
              required
              value={projectKey}
              onChange={(event) => setProjectKey(event.target.value)}
              placeholder="REL"
            />
          </label>
          <label>
            Dataset label
            <input
              required
              value={datasetLabel}
              onChange={(event) => setDatasetLabel(event.target.value)}
            />
          </label>
          <label>
            Target release
            <input
              required
              value={targetRelease}
              onChange={(event) => setTargetRelease(event.target.value)}
              placeholder="R2.4"
            />
          </label>
          <button type="submit" disabled={running}>
            {running ? "Investigating..." : "Assess release"}
          </button>
        </form>
      </section>

      {error && <div className="alert error">{error}</div>}

      {report && (
        <section className="report">
          <div className="reportHeader">
            <div>
              <p className="eyebrow">Generated report</p>
              <h2>{report.target_release}</h2>
            </div>
            <span className={`decision ${report.overall_decision.toLowerCase()}`}>
              {report.overall_decision}
            </span>
          </div>

          <div className="metrics">
            <span>{report.requirements.length} requirements</span>
            <span>{report.usage.execution_time_ms} ms</span>
            <span>{report.usage.model_calls} model calls</span>
          </div>

          <div className="requirements">
            {report.requirements.map((requirement) => (
              <article className="requirement" key={requirement.requirement_id}>
                <div className="requirementTitle">
                  <div>
                    <p className="requirementId">{requirement.requirement_id}</p>
                    <h3>{requirement.title}</h3>
                  </div>
                  <span className={`badge ${requirement.decision.toLowerCase()}`}>
                    {requirement.decision.replaceAll("_", " ")}
                  </span>
                </div>
                <p>{requirement.explanation}</p>

                {requirement.evidence.length > 0 && (
                  <div>
                    <h4>Evidence</h4>
                    {requirement.evidence.map((item) => (
                      <div className="evidence" key={`${item.ticket_key}-${item.comment_id}`}>
                        <strong>{item.ticket_key}</strong>
                        {item.comment_id && <span>Comment {item.comment_id}</span>}
                        <p>{item.summary}</p>
                        <small>{item.applicability}</small>
                      </div>
                    ))}
                  </div>
                )}

                {requirement.outstanding.length > 0 && (
                  <div>
                    <h4>Outstanding</h4>
                    <ul>
                      {requirement.outstanding.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </article>
            ))}
          </div>
        </section>
      )}
    </main>
  );
}
