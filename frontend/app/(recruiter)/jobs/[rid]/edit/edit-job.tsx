"use client";

import { useParams } from "next/navigation";

import { EditRequirementView } from "../../../clients/[id]/requirements/[rid]/edit/edit-requirement";

/** Editing a job opened from Jobs; saving returns to /jobs/[rid]. */
export function EditJob() {
  const { rid } = useParams<{ rid: string }>();
  return <EditRequirementView requirementId={rid} section="jobs" />;
}
