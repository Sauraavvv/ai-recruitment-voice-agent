/** "Acme Hiring" → "Acme Hiring's", "Sharma Associates" → "Sharma Associates'" */
export function possessive(name: string) {
  return /s$/i.test(name) ? `${name}'` : `${name}'s`;
}
