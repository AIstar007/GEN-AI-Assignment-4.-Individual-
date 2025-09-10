import React from "react";
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  AreaChart,
  Area,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { format, parseISO, isValid } from "date-fns";

// Smart Date Formatter
const smartFormat = (tick) => {
  try {
    const parsed = parseISO(tick);
    if (isValid(parsed)) return format(parsed, "MMM yyyy");
    return tick;
  } catch {
    return tick;
  }
};

// Number Formatter
const numberFormat = (value) => {
  if (value >= 1_000_000_000) return (value / 1_000_000_000).toFixed(1) + "B";
  if (value >= 1_000_000) return (value / 1_000_000).toFixed(1) + "M";
  if (value >= 1_000) return (value / 1_000).toFixed(1) + "K";
  return value;
};

// Custom Tooltip
const CustomTooltip = ({ active, payload, label }) => {
  if (active && payload && payload.length) {
    return (
      <div style={{ background: "#fff", padding: "8px 12px", border: "1px solid #ccc", borderRadius: "8px" }}>
        <p style={{ margin: 0, fontWeight: "bold" }}>{smartFormat(label)}</p>
        {payload.map((entry, index) => (
          <p key={`tooltip-${index}`} style={{ margin: 0, color: entry.color }}>
            {entry.name}: {numberFormat(entry.value)}
          </p>
        ))}
      </div>
    );
  }
  return null;
};

// Color Palette
const COLORS = ["#007bff", "#28a745", "#ff7300", "#ff0000", "#6f42c1", "#20c997", "#fd7e14"];

const ChartRender = ({ data, type = "line", xKey }) => {
  if (!data || data.length === 0) {
    return <p style={{ color: "#666", fontStyle: "italic" }}>No data available</p>;
  }

  const allKeys = Object.keys(data[0] || {});
  const yKeys = allKeys.filter((k) => k !== xKey);

  // Pie Chart expects "name" & "value"
  if (type === "pie") {
    const pieData =
      data.map((d) => ({ name: d[allKeys[0]], value: d[allKeys[1]] })) || [];
    return (
      <ResponsiveContainer width="100%" height={350}>
        <PieChart>
          <Tooltip />
          <Legend />
          <Pie data={pieData} dataKey="value" nameKey="name" outerRadius={120}>
            {pieData.map((_, i) => (
              <Cell key={i} fill={COLORS[i % COLORS.length]} />
            ))}
          </Pie>
        </PieChart>
      </ResponsiveContainer>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={350}>
      {type === "line" ? (
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e0e0e0" />
          <XAxis dataKey={xKey} tickFormatter={smartFormat} angle={-30} textAnchor="end" interval="preserveStartEnd" stroke="#555" />
          <YAxis stroke="#555" tickFormatter={numberFormat} />
          <Tooltip content={<CustomTooltip />} />
          <Legend />
          {yKeys.map((key, i) => (
            <Line key={key} type="monotone" dataKey={key} stroke={COLORS[i % COLORS.length]} strokeWidth={3} dot={{ r: 4 }} />
          ))}
        </LineChart>
      ) : type === "bar" ? (
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e0e0e0" />
          <XAxis dataKey={xKey} tickFormatter={smartFormat} angle={-30} textAnchor="end" interval="preserveStartEnd" stroke="#555" />
          <YAxis stroke="#555" tickFormatter={numberFormat} />
          <Tooltip content={<CustomTooltip />} />
          <Legend />
          {yKeys.map((key, i) => (
            <Bar key={key} dataKey={key} fill={COLORS[i % COLORS.length]} radius={[6, 6, 0, 0]} />
          ))}
        </BarChart>
      ) : type === "area" ? (
        <AreaChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e0e0e0" />
          <XAxis dataKey={xKey} tickFormatter={smartFormat} angle={-30} textAnchor="end" interval="preserveStartEnd" stroke="#555" />
          <YAxis stroke="#555" tickFormatter={numberFormat} />
          <Tooltip content={<CustomTooltip />} />
          <Legend />
          {yKeys.map((key, i) => (
            <Area key={key} type="monotone" dataKey={key} stroke={COLORS[i % COLORS.length]} fill={COLORS[i % COLORS.length]} />
          ))}
        </AreaChart>
      ) : null}
    </ResponsiveContainer>
  );
};

export default ChartRender;