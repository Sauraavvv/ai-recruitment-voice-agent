import { Suspense } from "react";

import { LoginForm } from "./login-form";

export const metadata = { title: "Log in · AI Recruitment Voice Agent" };

export default function LoginPage() {
  return (
    <main className="mx-auto w-full max-w-sm flex-1 px-4 py-16">
      <h1 className="mb-1 text-2xl font-semibold">Recruiter login</h1>
      <p className="mb-8 text-sm text-zinc-500">AI Recruitment Voice Agent</p>
      <Suspense>
        <LoginForm />
      </Suspense>
    </main>
  );
}
