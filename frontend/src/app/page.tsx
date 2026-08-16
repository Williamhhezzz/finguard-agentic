"use client";

import { useState, useEffect } from "react";

interface Transaction {
  transaction_id: string;
  cc_num: number;
  amt: number;
  city: string;
  job: string;
  velocity: number;
}

interface Escalation {
  transaction: Transaction;
  reasoning: string;
}

export default function ControlCenter() {
  const [escalations, setEscalations] = useState<Record<string, Escalation>>({});
  const [loading, setLoading] = useState(true);
  const [resolvingId, setResolvingId] = useState<string | null>(null);

  // Poll for active escalations
  useEffect(() => {
    const fetchEscalations = async () => {
      try {
        const response = await fetch("http://localhost:8000/api/escalations");
        if (!response.ok) throw new Error("API unreachable");
        
        const data = await response.json();
        setEscalations(data.escalations || {});
      } catch (error) {
        console.error("Failed to sync with Cognitive Engine:", error);
      } finally {
        setLoading(false);
      }
    };

    fetchEscalations();
    const interval = setInterval(fetchEscalations, 5000);
    return () => clearInterval(interval);
  }, []);

  // Dispatch Human Decision to FastAPI
  const handleResolve = async (threadId: string, decision: "APPROVE" | "BLOCK") => {
    setResolvingId(threadId);
    try {
      const response = await fetch(`http://localhost:8000/api/resolve/${threadId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision }),
      });

      if (!response.ok) {
        throw new Error(`Failed to resolve transaction: ${response.statusText}`);
      }

      // Optimistically remove the resolved card from the screen immediately
      setEscalations((prev) => {
        const updated = { ...prev };
        delete updated[threadId];
        return updated;
      });
    } catch (error) {
      console.error("Error dispatching resolution:", error);
      alert("Failed to submit decision to the Cognitive Engine.");
    } finally {
      setResolvingId(null);
    }
  };

  return (
    <main className="min-h-screen bg-neutral-950 text-neutral-50 p-8 font-sans">
      <header className="mb-12 border-b border-neutral-800 pb-6">
        <h1 className="text-3xl font-bold tracking-tight">FinGuard Human Control Center</h1>
        <p className="text-neutral-400 mt-2">Tier 2 Cognitive Engine — Awaiting Human Authority</p>
      </header>

      <section className="max-w-4xl mx-auto">
        {loading ? (
          <div className="text-neutral-500 animate-pulse">Establishing secure link to AI engine...</div>
        ) : Object.keys(escalations).length === 0 ? (
          <div className="p-8 border border-neutral-800 rounded-lg text-center text-neutral-400">
            No active escalations. The grid is secure.
          </div>
        ) : (
          <div className="space-y-6">
            {Object.entries(escalations).map(([threadId, data]) => {
              const isProcessing = resolvingId === threadId;

              return (
                <div key={threadId} className="bg-neutral-900 border border-neutral-700 rounded-xl p-6 shadow-2xl">
                  <div className="flex justify-between items-start mb-4">
                    <div>
                      <h2 className="text-xl font-semibold text-red-400">Ambiguity Detected</h2>
                      <span className="text-xs font-mono text-neutral-500">Thread: {threadId}</span>
                    </div>
                    <div className="text-right">
                      <div className="text-2xl font-bold">${data.transaction.amt.toFixed(2)}</div>
                      <div className="text-sm text-neutral-400">{data.transaction.city}</div>
                    </div>
                  </div>
                  
                  <div className="bg-black/50 rounded-lg p-4 mb-6 border border-neutral-800">
                    <h3 className="text-xs uppercase tracking-wider text-neutral-500 mb-2">AI Reasoning Failsafe</h3>
                    <p className="text-sm text-neutral-300 leading-relaxed">{data.reasoning}</p>
                  </div>

                  <div className="flex gap-4">
                    <button
                      onClick={() => handleResolve(threadId, "APPROVE")}
                      disabled={isProcessing}
                      className="flex-1 bg-green-900/30 hover:bg-green-800/40 text-green-400 border border-green-800/50 py-3 rounded-lg font-medium transition-colors disabled:opacity-50"
                    >
                      {isProcessing ? "TRANSMITTING..." : "AUTHORIZE (Approve)"}
                    </button>
                    <button
                      onClick={() => handleResolve(threadId, "BLOCK")}
                      disabled={isProcessing}
                      className="flex-1 bg-red-900/30 hover:bg-red-800/40 text-red-400 border border-red-800/50 py-3 rounded-lg font-medium transition-colors disabled:opacity-50"
                    >
                      {isProcessing ? "TRANSMITTING..." : "NEUTRALIZE (Block)"}
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>
    </main>
  );
}