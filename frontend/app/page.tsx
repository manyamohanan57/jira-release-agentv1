"use client";

import { FormEvent, useState } from "react";

type Requirement = {
  requirement_id: string;
  requirement_name: string;
  mandatory: boolean;
  status: "PASS" | "FAIL" | "INSUFFICIENT_EVIDENCE";
  reasoning: string;
  evidence: Array<{
    issue_key: string;
    evidence_details: string;
    source_type: string;
    comment_id?: string;
    summary: string;
  }>;
  missing_evidence: string[];
  confidence: number;
};

type Report = {
  report_id: string;
  project_key: string;
  dataset_label: string;
  target_release: string;
  commit: string;
  service: string;
  environment: string;
  prompt_version: string;
  assessment_summary: string;
  overall_decision: "READY" | "NEEDS_REVIEW" | "BLOCKED";
  requirements: Requirement[];
  tool_trace: Array<{ tool: string }>;
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
      const response = await fetch(`${API_URL}/assessment/run`, {
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
              <p className="reportContext">
                {report.service} · {report.environment} · commit {report.commit} · prompt {report.prompt_version}
              </p>
            </div>
            <span className={`decision ${report.overall_decision.toLowerCase()}`}>
              {report.overall_decision}
            </span>
          </div>

          <div className="metrics">
            <span>{report.requirements.length} requirements</span>
            <span>{report.usage.execution_time_ms} ms</span>
            <span>{report.usage.model_calls} model calls</span>
            <span>{report.tool_trace.length} Jira tool calls</span>
          </div>
          <p>{report.assessment_summary}</p>

          <div className="tableWrap">
            <table className="resultsTable">
              <thead>
                <tr>
                  <th scope="col">Requirement</th>
                  <th scope="col">Status</th>
                  <th scope="col">Assessment</th>
                  <th scope="col">Jira evidence</th>
                  <th scope="col">Missing evidence</th>
                  <th scope="col">Confidence</th>
                </tr>
              </thead>
              <tbody>
                {report.requirements.map((requirement) => (
                  <tr key={requirement.requirement_id}>
                    <th scope="row">
                      <span className="requirementId">{requirement.requirement_id}</span>
                      <strong>{requirement.requirement_name}</strong>
                      <small>{requirement.mandatory ? "Mandatory" : "Optional"}</small>
                    </th>
                    <td>
                      <span className={`badge ${requirement.status.toLowerCase()}`}>
                        {requirement.status.replaceAll("_", " ")}
                      </span>
                    </td>
                    <td>{requirement.reasoning}</td>
                    <td>
                      {requirement.evidence.length > 0 ? (
                        <ul className="tableList">
                          {requirement.evidence.map((item) => (
                            <li key={`${item.issue_key}-${item.comment_id ?? item.summary}`}>
                              <strong>{item.issue_key}</strong>
                              {item.comment_id && <small>Comment {item.comment_id}</small>}
                              <details>
                                <summary>{item.summary}</summary>
                                <p>{item.source_type}: {item.evidence_details}</p>
                              </details>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <span className="muted">No qualifying evidence cited</span>
                      )}
                    </td>
                    <td>
                      {requirement.missing_evidence.length > 0 ? (
                        <ul className="tableList">
                          {requirement.missing_evidence.map((item) => (
                            <li key={item}>{item}</li>
                          ))}
                        </ul>
                      ) : (
                        <span className="muted">None</span>
                      )}
                    </td>
                    <td>{Math.round(requirement.confidence * 100)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </main>
  );
}
