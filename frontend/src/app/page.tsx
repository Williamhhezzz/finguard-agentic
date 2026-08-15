export default function ControlCenter() {
  return (
    <main className="min-h-screen bg-neutral-900 text-white p-8">
      <header className="mb-8 border-b border-neutral-700 pb-4">
        <h1 className="text-3xl font-bold tracking-tight">FinGuard Control Center</h1>
        <p className="text-neutral-400 mt-1">Human-in-the-Loop Override Console</p>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* The Backlog Queue (Left Column) */}
        <div className="lg:col-span-1 border-r border-neutral-800 pr-8">
          <h2 className="text-xl font-semibold mb-4 text-neutral-300">Active Escalations</h2>
          <div className="animate-pulse flex space-x-4">
            <div className="flex-1 space-y-4 py-1">
              <div className="h-2 bg-neutral-700 rounded w-3/4"></div>
              <div className="space-y-2">
                <div className="h-2 bg-neutral-700 rounded"></div>
                <div className="h-2 bg-neutral-700 rounded w-5/6"></div>
              </div>
            </div>
          </div>
        </div>

        {/* The Hero Card (Right Columns) */}
        <div className="lg:col-span-2">
           <h2 className="text-xl font-semibold mb-4 text-yellow-500">Awaiting Authority</h2>
           <div className="h-64 border border-neutral-700 rounded-lg bg-neutral-800/50 flex items-center justify-center">
              <p className="text-neutral-500">Select an escalation from the queue...</p>
           </div>
        </div>
      </div>
    </main>
  );
}