// Friendly aliases over the generated OpenAPI types (`npm run gen:types` / `make types`).
import type { components } from "./api";

type Schemas = components["schemas"];

export type User = Schemas["UserOut"];
export type Candidate = Schemas["CandidateOut"];
export type CandidateCreate = Schemas["CandidateCreate"];
export type CandidateUpdate = Schemas["CandidateUpdate"];
export type ScreeningStatus = Schemas["ScreeningStatus"];
export type PageMeta = Schemas["PageMeta"];
export type Job = Schemas["JobOut"];
export type JobCreate = Schemas["JobCreate"];
export type JobUpdate = Schemas["JobUpdate"];
export type ScreeningQuestion = Schemas["ScreeningQuestion"];
export type DefaultQuestionsResult = Schemas["DefaultQuestionsOut"];
export type ImportPreview = Schemas["ImportOut"];
export type ImportRow = Schemas["ImportRow"];
export type RowStatus = Schemas["RowStatus"];
export type DashboardSummary = Schemas["DashboardSummary"];
export type CallsOnDay = Schemas["CallsOnDay"];
