import { useState, useEffect, useRef } from 'react';

const INITIAL_TELEMETRY = {
  timestamp: 0,
  rpm: 5200,
  map: 28.5, // inHg
  oil_pressure: 4.2, // bar
  oil_temp: 88, // °C
  fuel_flow: 22.4, // L/h
  altitude: 4500, // ft
  cht: [115, 118, 122, 116], // Cylinder Head Temp °C
  egt: [780, 792, 810, 785], // Exhaust Gas Temp °C
  rul_hours: 420.5,
  health_index: 96,
  anomaly_score: 0.04,
  status: "NORMAL" // "NORMAL" | "WARNING" | "CRITICAL"
};

export function useTelemetry(socketUrl = 'ws://localhost:8000/ws/telemetry') {
  const [telemetry, setTelemetry] = useState(INITIAL_TELEMETRY);
  const [isConnected, setIsConnected] = useState(false);
  const [history, setHistory] = useState([]);
  const socketRef = useRef(null);

  useEffect(() => {
    let ws;
    let fallbackInterval;

    try {
      ws = new WebSocket(socketUrl);
      socketRef.current = ws;

      ws.onopen = () => {
        setIsConnected(true);
      };

      ws.onmessage = (event) => {
        const payload = JSON.parse(event.data);
        setTelemetry(payload);
        setHistory((prev) => [...prev.slice(-50), payload]);
      };

      ws.onerror = () => {
        setIsConnected(false);
      };

      ws.onclose = () => {
        setIsConnected(false);
      };
    } catch {
      setIsConnected(false);
    }

    // Fallback: If backend is offline, simulate smooth telemetry ticks for UI dev
    fallbackInterval = setInterval(() => {
      if (!socketRef.current || socketRef.current.readyState !== WebSocket.OPEN) {
        setTelemetry((prev) => {
          const jitter = (Math.random() - 0.5) * 2;
          const next = {
            ...prev,
            timestamp: prev.timestamp + 1,
            rpm: Math.round(5200 + jitter * 20),
            cht: prev.cht.map((t) => Number((t + jitter * 0.4).toFixed(1))),
            oil_temp: Number((prev.oil_temp + jitter * 0.1).toFixed(1)),
            oil_pressure: Number((prev.oil_pressure + jitter * 0.05).toFixed(1))
          };
          setHistory((h) => [...h.slice(-50), next]);
          return next;
        });
      }
    }, 200); // Ticks every 200ms to mimic high-frequency MAVLink data

    return () => {
      if (ws) ws.close();
      clearInterval(fallbackInterval);
    };
  }, [socketUrl]);

  return { telemetry, history, isConnected };
}