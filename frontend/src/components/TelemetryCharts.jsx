import React from 'react';
import { LineChart, Line, YAxis, ResponsiveContainer } from 'recharts';

export default function TelemetryCharts({ history }) {
  return (
    <div className="flex flex-col h-full gap-4">
      {/* RPM Graph */}
      <div className="flex-1 border border-gcs-border bg-gcs-panel p-4 flex flex-col relative">
        <span className="absolute top-4 left-4 text-xs font-mono text-gcs-text">RPM</span>
        <div className="flex-1 mt-6">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={history}>
              <YAxis domain={['dataMin - 100', 'dataMax + 100']} hide />
              <Line type="monotone" dataKey="rpm" stroke="#10b981" strokeWidth={2} dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* CHT Cylinder 3 Graph */}
      <div className="flex-1 border border-gcs-red/50 bg-gcs-red/5 p-4 flex flex-col relative">
        <span className="absolute top-4 left-4 text-xs font-mono text-gcs-red">CYLINDER 3 TEMPERATURE</span>
        <span className="absolute top-4 right-4 text-xs font-mono bg-gcs-red text-black px-1">Peak: 126°C</span>
        <div className="flex-1 mt-6">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={history}>
              <YAxis domain={[110, 140]} hide />
              <Line type="monotone" dataKey={(d) => d.cht[2]} stroke="#ef4444" strokeWidth={2} dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}