import Link from "next/link";

import { Logo } from "@/components/logo";

import { WavePanel } from "../login/wave-panel";
import { SignupForm } from "./signup-form";

export const metadata = { title: "Sign up · CallZest" };

export default function SignupPage() {
  return (
    <main className="grid min-h-screen flex-1 bg-black font-sans text-white lg:grid-cols-2">
      {/* Same layout as the login page: a card inset from the top, left and bottom edges */}
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
            Create your account
          </h1>
          <p className="font-display mt-2 mb-9 text-center text-zinc-500">
            Set up your company. You&apos;ll be its super admin.
          </p>
          <SignupForm />
          <p className="mt-8 text-center text-sm text-zinc-500">
            Already have an account?{" "}
            <Link href="/login" className="font-medium text-white hover:underline">
              Log in
            </Link>
          </p>
        </div>
      </section>
    </main>
  );
}
