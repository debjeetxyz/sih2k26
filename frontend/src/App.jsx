import React from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import LoginScreen from './components/LoginScreen';
import FlightDashboard from './components/FlightDashboard';

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-gcs-bg text-gcs-text font-sans overflow-hidden">
        <Routes>
          <Route path="/" element={<LoginScreen />} />
          <Route path="/dashboard" element={<FlightDashboard />} />
        </Routes>
      </div>
    </BrowserRouter>
  );
}