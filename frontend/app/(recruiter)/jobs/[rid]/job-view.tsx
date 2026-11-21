"use client";

import { useParams } from "next/navigation";

import { RequirementView } from "../../clients/[id]/requirements/[rid]/requirement-detail";

/** A job opened from Jobs: the requirement page, kept under /jobs. */
export function JobView() {
  const { rid } = useParams<{ rid: string }>();
  return <RequirementView requirementId={rid} section="jobs" />;
}
