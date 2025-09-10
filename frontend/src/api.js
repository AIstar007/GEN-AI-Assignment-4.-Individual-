const API_BASE = import.meta.env.VITE_API_BASE || "/api";

/**
 * Translate a natural language query into either:
 *  - SQL query (plain type)
 *  - Forecast request (forecast type)
 */
export async function translateQuery(query) {
  const res = await fetch(`${API_BASE}/translate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  const data = await res.json();

  return {
    type: data.type || "plain",  // plain or forecast
    sql: data.sql || null,
    used_llm: data.used_llm || false,
    debug: data.debug || {},
  };
}

/**
 * Run a SQL or Forecast query on the backend.
 */
export async function runSQL(sql, used_llm = false, type = "plain") {
  const res = await fetch(`${API_BASE}/run-sql`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ type, sql, used_llm }),
  });
  if (!res.ok) throw new Error(`SQL API error: ${res.status}`);
  return await res.json();
}