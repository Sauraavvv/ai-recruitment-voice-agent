import { CallsList } from "./calls-list";

export const metadata = { title: "Screening calls · HireCall" };

export default function CallsPage() {
  return <CallsList purpose="screening" />;
}
