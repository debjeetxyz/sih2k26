import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Shield, Lock } from 'lucide-react';

export default function LoginScreen() {
  const navigate = useNavigate();
  const [role, setRole] = useState('Propulsion Engineer');

  const handleLogin = (e) => {
    e.preventDefault();
    // Navigate straight to the dashboard when LOGIN is clicked
    navigate('/dashboard');
  };

  return (
    <div className="h-screen w-screen flex flex-col items-center justify-center bg-gcs-bg relative">
      {/* Top Status Bar */}
      <div className="absolute top-4 right-4 flex space-x-2 text-xs font-mono">
        <span className="px-2 py-1 border border-gcs-border text-gcs-amber bg-gcs-panel">NETWORK: SECURE (VPN: ACTIVE)</span>
        <span className="px-2 py-1 border border-gcs-border text-gcs-green bg-gcs-panel">SYSTEM STATUS: OPERATIONAL</span>
      </div>

      {/* Main Login Panel */}
      <div className="w-[600px] border border-gcs-border bg-gcs-panel rounded-lg shadow-2xl p-6 relative overflow-hidden">
        {/* Decorative HUD corners */}
        <div className="absolute top-0 left-0 w-4 h-4 border-t-2 border-l-2 border-gcs-highlight opacity-30 m-2" />
        <div className="absolute top-0 right-0 w-4 h-4 border-t-2 border-r-2 border-gcs-highlight opacity-30 m-2" />
        <div className="absolute bottom-0 left-0 w-4 h-4 border-b-2 border-l-2 border-gcs-highlight opacity-30 m-2" />
        <div className="absolute bottom-0 right-0 w-4 h-4 border-b-2 border-r-2 border-gcs-highlight opacity-30 m-2" />

        <div className="flex items-center space-x-3 mb-6 border-b border-gcs-border pb-4">
          <Shield className="w-8 h-8 text-gcs-highlight" />
          <h1 className="text-2xl font-bold text-gcs-highlight tracking-widest">DEFENCE SECURITY CHECK</h1>
          <Lock className="w-5 h-5 text-gcs-text ml-auto" />
        </div>

        <form onSubmit={handleLogin} className="space-y-6">
          <div className="grid grid-cols-2 gap-6">
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-mono text-gcs-text mb-1">ROLE SELECTION</label>
                <select 
                  value={role}
                  onChange={(e) => setRole(e.target.value)}
                  className="w-full bg-gcs-bg border border-gcs-border p-2 text-sm text-gcs-highlight font-mono focus:border-gcs-blue outline-none"
                >
                  <option>UAV Operator</option>
                  <option>Propulsion Engineer</option>
                </select>
              </div>
              <div>
                <label className="block text-xs font-mono text-gcs-text mb-1">USERNAME</label>
                <input type="text" defaultValue="operator_alpha" className="w-full bg-gcs-bg border border-gcs-border p-2 text-sm text-gcs-highlight font-mono focus:border-gcs-blue outline-none" />
              </div>
            </div>

            {/* RSA Key Graphic Placeholder */}
            <div className="border border-gcs-border bg-gcs-bg p-4 flex flex-col items-center justify-center rounded">
              <div className="w-24 h-10 border border-gcs-red/50 bg-gcs-red/10 flex items-center justify-center text-gcs-red font-mono tracking-widest rounded mb-2">
                123-456
              </div>
              <span className="text-xs font-mono text-gcs-text">AWAITING KEY INPUT</span>
            </div>
          </div>

          <div>
            <label className="block text-xs font-mono text-gcs-text mb-1">RSA PASSCODE</label>
            <input type="password" placeholder="••••••••" className="w-full bg-gcs-bg border border-gcs-border p-2 text-sm text-gcs-highlight font-mono focus:border-gcs-blue outline-none mb-6" />
          </div>

          <div className="flex space-x-4">
            <button type="submit" className="flex-1 bg-gcs-highlight text-black font-bold py-2 hover:bg-white transition-colors tracking-widest font-mono cursor-pointer">
              LOGIN
            </button>
            <button type="button" className="flex-1 bg-gcs-bg border border-gcs-border text-gcs-highlight font-bold py-2 hover:bg-gcs-border transition-colors tracking-widest font-mono cursor-pointer">
              RESET KEY
            </button>
          </div>
        </form>
        
        <div className="text-center mt-6 text-[10px] text-gcs-text font-mono uppercase tracking-widest">
          SECURE ACCESS PORTAL - AUTHORIZED PERSONNEL ONLY
        </div>
      </div>
    </div>
  );
}