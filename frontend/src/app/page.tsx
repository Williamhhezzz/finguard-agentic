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

interface SystemMetrics {
  tier2_total: number;
  auto_resolved_ai: number;
  human_resolved: number;
  total_escalated_human: number;
  pending_human_review: number;
  total_approved: number;
  total_blocked: number;
}

export default function ControlCenter() {
  const [escalations, setEscalations] = useState<Record<string, Escalation>>({});
  const [metrics, setMetrics] = useState<SystemMetrics>({
    tier2_total: 0,
    auto_resolved_ai: 0,
    human_resolved: 0,
    total_escalated_human: 0,
    pending_human_review: 0,
    total_approved: 0,
    total_blocked: 0,
  });
  const [loading, setLoading] = useState(true);
  const [resolvingId, setResolvingId] = useState<string | null>(null);

  const fetchData = async () => {
    try {
      const [escRes, metRes] = await Promise.all([
        fetch("http://localhost:8000/api/escalations"),
        fetch("http://localhost:8000/api/metrics"),
      ]);
      
      if (!escRes.ok || !metRes.ok) throw new Error("API unreachable");
      
      const escData = await escRes.json();
      const metData = await metRes.json();
      
      setEscalations(escData.escalations || {});
      setMetrics(metData);
    } catch (error) {
      console.error("Failed to sync data:", error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, []);

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

      setEscalations((prev) => {
        const updated = { ...prev };
        delete updated[threadId];
        return updated;
      });
      
      fetchData();
    } catch (error) {
      console.error("Error dispatching resolution:", error);
      alert("Failed to submit decision.");
    } finally {
      setResolvingId(null);
    }
  };

  return (
    <main className="min-h-screen bg-neutral-950 text-neutral-50 p-8 font-sans">
      <header className="mb-8 border-b border-neutral-800 pb-6 flex justify-between items-end max-w-5xl mx-auto">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-neutral-100">FinGuard Fraud Operations</h1>
          <p className="text-neutral-400 mt-2">Live AI Risk Analysis & Case Management</p>
        </div>
        <div className="text-xs text-neutral-500 font-mono mb-1">
          <span className="inline-block w-2 h-2 rounded-full bg-emerald-500 animate-pulse mr-2"></span>
          System Online
        </div>
      </header>

      <section className="max-w-5xl mx-auto mb-12">
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-5">
            <p className="text-xs text-neutral-400 uppercase font-semibold tracking-wider">Cases Evaluated by AI</p>
            <p className="text-3xl font-bold text-neutral-100 mt-2">{metrics.tier2_total}</p>
            <p className="text-xs text-blue-400 mt-2">Total transactions checked</p>
          </div>
          <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-5">
            <p className="text-xs text-neutral-400 uppercase font-semibold tracking-wider">Auto-Resolved</p>
            <p className="text-3xl font-bold text-green-400 mt-2">{metrics.auto_resolved_ai}</p>
            <p className="text-xs text-neutral-500 mt-2">Handled without human review</p>
          </div>
          <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-5">
            <p className="text-xs text-neutral-400 uppercase font-semibold tracking-wider">Escalated to Human</p>
            <p className="text-3xl font-bold text-indigo-400 mt-2">{metrics.total_escalated_human}</p>
            <p className="text-xs text-indigo-400/80 mt-2">Total sent to analyst</p>
          </div>
          <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-5">
            <p className="text-xs text-neutral-400 uppercase font-semibold tracking-wider">Pending Review</p>
            <p className="text-3xl font-bold text-yellow-500 mt-2">{metrics.pending_human_review}</p>
            <p className="text-xs text-yellow-500/70 mt-2">Awaiting analyst action</p>
          </div>
          <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-5">
            <p className="text-xs text-neutral-400 uppercase font-semibold tracking-wider">Transactions Declined</p>
            <p className="text-3xl font-bold text-red-500 mt-2">{metrics.total_blocked}</p>
            <p className="text-xs text-red-500/70 mt-2">Suspicious activity stopped</p>
          </div>
        </div>
      </section>

      <section className="max-w-4xl mx-auto">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-neutral-500 mb-6 border-b border-neutral-800 pb-2">
          Cases Requiring Attention ({Object.keys(escalations).length})
        </h2>

        {loading ? (
          <div className="text-neutral-500 animate-pulse text-center p-8 border border-neutral-800 rounded-xl">
            Loading active cases...
          </div>
        ) : Object.keys(escalations).length === 0 ? (
          <div className="p-12 border border-neutral-800 rounded-xl bg-neutral-900/30 text-center text-neutral-500">
            No pending cases. All active transactions have been resolved autonomously.
          </div>
        ) : (
          <div className="space-y-6">
            {Object.entries(escalations).map(([threadId, data]) => {
              const isProcessing = resolvingId === threadId;

              return (
                <div key={threadId} className="bg-neutral-900 border border-neutral-700 rounded-xl p-6 shadow-2xl">
                  <div className="flex justify-between items-start mb-4">
                    <div>
                      <span className="inline-block px-2 py-1 bg-yellow-500/10 text-yellow-500 text-xs font-bold tracking-wider rounded mb-2 border border-yellow-500/20">
                        MANUAL REVIEW REQUIRED
                      </span>
                      <h2 className="text-xl font-semibold text-neutral-100">Action Required: Anomaly Detected</h2>
                      <span className="text-xs font-mono text-neutral-500">Case ID: {threadId}</span>
                    </div>
                    <div className="text-right">
                      <div className="text-2xl font-bold text-yellow-500">${data.transaction.amt.toFixed(2)}</div>
                      <div className="text-sm text-neutral-400">{data.transaction.city}</div>
                      <div className="text-xs text-neutral-500 mt-1">Card: {data.transaction.cc_num}</div>
                    </div>
                  </div>
                  
                  <div className="bg-black/50 rounded-lg p-4 mb-6 border border-neutral-800">
                    <h3 className="text-xs uppercase tracking-wider text-blue-400 font-bold mb-2">AI Risk Analysis:</h3>
                    <p className="text-sm text-neutral-300 leading-relaxed">{data.reasoning}</p>
                  </div>

                  <div className="flex gap-4">
                    <button
                      onClick={() => handleResolve(threadId, "APPROVE")}
                      disabled={isProcessing}
                      className="flex-1 bg-green-900/30 hover:bg-green-800/40 text-green-400 border border-green-800/50 py-3 rounded-lg font-medium transition-colors disabled:opacity-50"
                    >
                      {isProcessing ? "Processing..." : "Approve Transaction"}
                    </button>
                    <button
                      onClick={() => handleResolve(threadId, "BLOCK")}
                      disabled={isProcessing}
                      className="flex-1 bg-red-900/30 hover:bg-red-800/40 text-red-400 border border-red-800/50 py-3 rounded-lg font-medium transition-colors disabled:opacity-50"
                    >
                      {isProcessing ? "Processing..." : "Decline Transaction"}
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