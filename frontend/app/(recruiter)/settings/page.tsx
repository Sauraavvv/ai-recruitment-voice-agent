import { AdminOnly } from "@/components/admin-only";

import { SettingsView } from "./settings-view";

export const metadata = { title: "Settings · CallZest" };

export default function SettingsPage() {
  return (
    <AdminOnly title="Settings">
      <SettingsView />
    </AdminOnly>
  );
}
