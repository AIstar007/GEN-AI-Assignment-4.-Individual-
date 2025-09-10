import React, { useState, useEffect, useRef } from "react";
import ChartRender from "./ChartRender.jsx";
import { translateQuery, runSQL } from "./api";
import sampleQueries from "./sample_queries";
import "./index.css";

// 🔹 Enhanced Reusable Table Renderer
function ResultTable({ columns, rows, emptyMsg }) {
  if (!rows || rows.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-icon">📊</div>
        <p className="muted">{emptyMsg}</p>
      </div>
    );
  }
  return (
    <div className="table-wrapper enhanced-table">
      <table className="styled-table">
        <thead>
          <tr>
            {columns.map((c, i) => (
              <th key={i}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="table-row-enhanced">
              {r.map((cell, j) => (
                <td key={j}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Enhanced Loading Component
function LoadingDots() {
  return (
    <div className="loading-enhanced">
      <div className="typing-dots">
        <span></span>
        <span></span>
        <span></span>
      </div>
      <p className="loading-text">Analyzing your query...</p>
    </div>
  );
}

export default function App() {
  const [queryType, setQueryType] = useState("plain");
  const [query, setQuery] = useState("");
  const [translateResult, setTranslateResult] = useState(null);
  const [sqlResult, setSqlResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");
  const [messages, setMessages] = useState([]);

  const messagesEndRef = useRef(null);
  const textareaRef = useRef(null);

  // Auto-scroll with smooth animation
  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, loading]);

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${Math.min(
        textareaRef.current.scrollHeight,
        120
      )}px`;
    }
  }, [query]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!query.trim()) return;

    // Add user message
    setMessages((prev) => [
      ...prev,
      {
        type: "user",
        text: query,
        timestamp: new Date().toLocaleTimeString(),
      },
    ]);

    setLoading(true);
    setTranslateResult(null);
    setSqlResult(null);
    setError("");

    try {
      const tr = await translateQuery(query);
      setTranslateResult(tr);

      // ✅ Plain queries
      if (tr.type === "plain" && tr.sql) {
        const res = await runSQL(tr.sql, tr.used_llm, "sql");
        setSqlResult(res);

        const PlainMessage = () => {
          const [showJson, setShowJson] = useState(false);
          const [chartType, setChartType] = useState("line");

          const numericColumnIndex = res.columns.findIndex(
            (col, idx) =>
              res.rows[0] &&
              !isNaN(res.rows[0][idx]?.toString().replace(/[$,]/g, ""))
          );

          const chartData =
            numericColumnIndex !== -1
              ? res.rows.map((r) => ({
                  x: r[0],
                  y:
                    parseFloat(
                      r[numericColumnIndex]?.toString().replace(/[$,]/g, "")
                    ) || 0,
                }))
              : [];

          return (
            <div className="results-container-enhanced">
              <h3>📊 Query Results ({res.rows?.length || 0} rows)</h3>

              {showJson ? (
                <pre>{JSON.stringify(res, null, 2)}</pre>
              ) : (
                <div className="table-chart-container">
                  <ResultTable
                    columns={res.columns}
                    rows={res.rows}
                    emptyMsg="No rows returned."
                  />
                  {chartData.length > 0 && (
                    <ChartRender
                      type={chartType}
                      data={chartData}
                      xKey="x"
                      yKey={["y"]}
                    />
                  )}
                </div>
              )}
            </div>
          );
        };

        setMessages((prev) => [
          ...prev,
          {
            type: "bot",
            content: <PlainMessage />,
            timestamp: new Date().toLocaleTimeString(),
          },
        ]);
      }

      // ✅ Forecast queries
      else if (tr.type === "forecast") {
        let res = { historical: [], forecast: [] };
        try {
          if (tr.sql) {
            const apiRes = await runSQL(tr.sql, tr.used_llm, "forecast");

            // 🔹 Normalize forecast response
            if (apiRes.forecast_result) {
              const hist = apiRes.forecast_result.historical || [];
              const fore = (apiRes.forecast_result.forecast || []).map((r) => ({
                date: r.date || r.ds,
                value: r.value ?? r.TimeGPT,
              }));
              res = { historical: hist, forecast: fore };
            } else {
              const hist = apiRes.historical || [];
              const fore = (apiRes.forecast || []).map((r) => ({
                date: r.date || r.ds,
                value: r.value ?? r.TimeGPT,
              }));
              res = { historical: hist, forecast: fore };
            }
          }
        } catch {
          res = { historical: [], forecast: [] };
        }

        setSqlResult(res);

        const ForecastMessage = () => {
          const [chartType, setChartType] = useState("line");

          const chartData = [
            ...(res.historical || []).map((r) => ({
              date: r.date,
              actual: r.value,
            })),
            ...(res.forecast || []).map((r) => ({
              date: r.date,
              predicted: r.value,
            })),
          ];

          return (
            <div className="results-container-enhanced">
              <h3>
                🔮 Forecast Results ({res.historical?.length || 0} historical,{" "}
                {res.forecast?.length || 0} predicted)
              </h3>

              <div className="forecast-tables">
                <div>
                  <h4>📈 Historical Data</h4>
                  <ResultTable
                    columns={["Date", "Value"]}
                    rows={(res.historical || []).map((r) => [r.date, r.value])}
                    emptyMsg="No historical data"
                  />
                </div>

                <div>
                  <h4>🔮 Forecast Data</h4>
                  <ResultTable
                    columns={["Date", "Predicted Value"]}
                    rows={(res.forecast || []).map((r) => [r.date, r.value])}
                    emptyMsg="No forecast data"
                  />
                </div>
              </div>

              {chartData.length > 0 && (
                <ChartRender
                  type={chartType}
                  data={chartData}
                  xKey="date"
                  yKey={["actual", "predicted"]}
                />
              )}
            </div>
          );
        };

        setMessages((prev) => [
          ...prev,
          {
            type: "bot",
            content: <ForecastMessage />,
            timestamp: new Date().toLocaleTimeString(),
          },
        ]);
      }
    } catch (err) {
      setError(err.message || "Failed to connect to backend");
      setMessages((prev) => [
        ...prev,
        {
          type: "bot",
          text: `❌ ${err.message || "Failed to connect"}`,
          timestamp: new Date().toLocaleTimeString(),
          isError: true,
        },
      ]);
    } finally {
      setLoading(false);
      setQuery("");
    }
  };

  return (
    <div className="chat-wrapper enhanced-wrapper">
      <div className="chat-header">
        <h2>🤖 NL to SQL + Forecast Detector</h2>
      </div>

      <div className="control-panel">
        <label>
          🎯 Query Type:
          <select
            value={queryType}
            onChange={(e) => setQueryType(e.target.value)}
          >
            <option value="plain">📊 Plain Query</option>
            <option value="forecast">🔮 Forecast Query</option>
          </select>
        </label>
        <label>
          💡 Sample Query:
          <select value={query} onChange={(e) => setQuery(e.target.value)}>
            <option value="">-- Choose a sample query --</option>
            {sampleQueries[queryType].map((q, i) => (
              <option key={i} value={q}>
                {q}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="chat-messages">
        {messages.map((msg, i) => (
          <div key={i} className={`message-bubble ${msg.type}`}>
            {msg.text ? <p>{msg.text}</p> : msg.content}
          </div>
        ))}
        {loading && <LoadingDots />}
        <div ref={messagesEndRef} />
      </div>

      <form onSubmit={handleSubmit} className="chat-input">
        <textarea
          ref={textareaRef}
          rows="1"
          placeholder="Ask me anything about your data..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <button type="submit" disabled={loading}>
          🚀
        </button>
      </form>
    </div>
  );
}