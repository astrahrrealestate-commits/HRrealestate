/** What a signed-in person may see. When it changes, data cached under the old value must go. */
export function profileKey(profile: {
  email: string;
  company_id?: string;
  isAdmin: boolean;
  sections: string[];
}): string {
  return JSON.stringify([profile.company_id, profile.email, profile.isAdmin, [...profile.sections].sort()]);
}
