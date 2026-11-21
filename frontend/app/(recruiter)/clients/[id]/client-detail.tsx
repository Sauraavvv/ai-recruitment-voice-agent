"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { ErrorState, Skeleton } from "@/components/states";
import { BackLink, PageHeader, buttonClass } from "@/components/ui";
import { useLoad } from "@/lib/use-load";
import { getClient } from "@/services/clients";

import { ClientProfileCard } from "../client-card";
import { CLIENT_STATUS } from "../form-kit";
import { ClientOverview } from "./client-overview";

/** A client's page: its numbers and requirements on the left, its card on the right. */
export function ClientDetail() {
  const { id } = useParams<{ id: string }>();
  const { data: client, error, reload } = useLoad(`client:${id}`, () => getClient(id));

  if (error && !client) return <ErrorState error={error} onRetry={reload} />;
  if (!client) return <Skeleton className="h-96 rounded-3xl" />;

  const status = CLIENT_STATUS[client.status];
  return (
    <>
      <BackLink href="/clients">All clients</BackLink>
      <PageHeader title={client.name}>
        <Link href={`/clients/${client.id}/edit`} className={buttonClass("secondary")}>
          Edit
        </Link>
      </PageHeader>

      {/* Both columns stretch to the taller one, so their bottoms line up */}
      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_380px]">
        <ClientOverview clientId={client.id} />

        <div className="[&>div]:h-full">
          <ClientProfileCard
            data={client}
            badges={
              <>
                <span
                  className={`rounded-full px-2.5 py-0.5 text-[11px] font-medium ${status.tone}`}
                >
                  {status.label}
                </span>
                {client.is_confidential && (
                  <span className="rounded-full bg-white/5 px-2.5 py-0.5 text-[11px] font-medium text-zinc-300">
                    Confidential
                  </span>
                )}
              </>
            }
          />
        </div>
      </div>
    </>
  );
}
