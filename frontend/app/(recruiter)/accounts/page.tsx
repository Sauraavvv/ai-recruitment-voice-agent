import { Suspense } from "react";

import { AccountsView } from "./accounts-view";

export const metadata = { title: "Accounts · HireCall" };

export default function AccountsPage() {
  return (
    // AccountsView makes a random starting password: render it at request time, not prerendered
    <Suspense fallback={<div className="h-40 rounded-3xl bg-[#18191c]" />}>
      <AccountsView />
    </Suspense>
  );
}
