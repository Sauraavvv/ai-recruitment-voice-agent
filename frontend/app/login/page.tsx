import { Suspense } from "react";

import { Logo } from "@/components/logo";

import { WavePanel } from "./wave-panel";
import { LoginForm } from "./login-form";

export const metadata = { title: "Log in · HireCall" };

export default function LoginPage() {
  return (
    <main className="grid min-h-screen flex-1 bg-black font-sans text-white lg:grid-cols-2">
      {/* A card inset from the top, left and bottom edges */}
      <section className="hidden py-4 pl-4 lg:flex">
        <div className="flex-1 overflow-hidden rounded-3xl">
          <WavePanel>
            <Logo className="text-white" markClassName="h-11 w-11" textClassName="text-5xl" />
          </WavePanel>
        </div>
      </section>
      <section className="flex items-center justify-center px-6 py-16">
        <div className="w-full max-w-[360px]">
          <div className="mb-10 flex justify-center lg:hidden">
            <Logo className="text-white" markClassName="h-7 w-7" textClassName="text-xl" />
          </div>
          <h1 className="font-display text-center text-[26px] font-semibold tracking-tight">
            Log in to your account
          </h1>
          <p className="font-display mt-2 mb-9 text-center text-zinc-500">
            Welcome back! Please enter your details.
          </p>
          <Suspense>
            <LoginForm />
          </Suspense>
          <p className="mt-8 text-center text-sm text-zinc-500">
            No account? Ask your administrator to create one.
          </p>
        </div>
      </section>
    </main>
  );
}
