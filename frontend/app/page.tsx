import { SystemStatus } from "./system-status";

export default function Home() {
  return (
    <main className="mx-auto w-full max-w-xl flex-1 px-4 py-12">
      <h1 className="text-2xl font-semibold">AI Recruitment Voice Agent</h1>
      <p className="mt-1 mb-8 text-sm text-zinc-500">System status</p>
      <SystemStatus />
    </main>
  );
}
