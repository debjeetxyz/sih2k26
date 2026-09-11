import React from 'react';
import { ShieldAlert } from 'lucide-react';
import { useTelemetry } from '../hooks/useTelemetry';
import EngineDigitalTwin from './EngineDigitalTwin';
import TelemetryCharts from './TelemetryCharts';

export default function FlightDashboard() {
  const { telemetry, history } = useTelemetry();

  return (
    <div className="h-screen w-screen bg-gcs-bg flex flex-col font-mono text-sm overflow-hidden">
      {/* Header */}
      <header className="h-12 border-b border-gcs-border bg-gcs-panel flex items-center px-6 justify-between">
        <div className="flex items-center space-x-4 text-gcs-text">
          <span>ANALYSIS &gt; FLIGHT REVIEW | AF-142B | 2026-09-11</span>
        </div>
        <div className="flex items-center space-x-4">
          <span className="text-gcs-text">USER: PROPULSION ENG | GCS: SECURE</span>
          <span className="bg-gcs-red/20 text-gcs-red px-3 py-1 border border-gcs-red/50">SYSTEM ALERT</span>
        </div>
      </header>

      {/* Main Grid Layout */}
      <div className="flex-1 p-6 grid grid-cols-12 gap-6 min-h-0">
        
        {/* Left Column: Telemetry Charts */}
        <div className="col-span-3 flex flex-col h-full">
          <div className="mb-2 text-gcs-text tracking-widest border-b border-gcs-border pb-2 flex justify-between">
            <span>TELEMETRY</span>
            <span>...</span>
          </div>
          <div className="flex-1 min-h-0">
            <TelemetryCharts history={history} />
          </div>
        </div>

        {/* Center Column: 3D Engine Model */}
        <div className="col-span-6 flex flex-col h-full">
          <div className="mb-2 text-gcs-text tracking-widest border-b border-gcs-border pb-2 flex justify-between">
            <span>4 CYLINDER AERO-PISTON UAV ENGINE</span>
            <span className="text-gcs-amber border border-gcs-amber px-2">SAFE OPERATION COMPROMISED</span>
          </div>
          <div className="flex-1 min-h-0">
            <EngineDigitalTwin telemetry={telemetry} />
          </div>
        </div>

        {/* Right Column: Alert Panel */}
        <div className="col-span-3 flex flex-col h-full">
          <div className="mb-2 text-gcs-text tracking-widest border-b border-gcs-border pb-2">
            <span>ALERT TICKET</span>
          </div>
          <div className="border border-gcs-red p-4 bg-gcs-red/5">
            <div className="flex items-center space-x-2 text-gcs-red mb-6">
              <ShieldAlert className="w-5 h-5" />
              <span className="font-bold tracking-widest">!! ALERT: CYLINDER 3 ANOMALY !!</span>
            </div>
            <div className="space-y-4 text-gcs-highlight">
              <p>DATE: 2026-09-11</p>
              <p>FLIGHT ID: AF-142B</p>
              <p>URGENCY: <span className="text-gcs-red">CRITICAL</span></p>
              <p>SYSTEM: ENGINE</p>
              <div className="h-px bg-gcs-border my-4" />
              <p>FAULT: OVERHEAT/VALVE MISFIRE</p>
              <p className="text-gcs-text">DESCRIPTION: CYLINDER 3 EXCEEDED MAX TEMP. POWER LOSS DETECTED.</p>
              <p className="text-gcs-amber mt-4">RECOMMENDED ACTION: IMMEDIATE ENGINE INSPECTION & VALVE CHECK.</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}