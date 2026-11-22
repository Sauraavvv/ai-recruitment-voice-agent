import { CallsList } from "../calls/calls-list";

export const metadata = { title: "Telephonic round · HireCall" };

export default function TelephonicRoundPage() {
  return <CallsList purpose="telephonic" />;
}
