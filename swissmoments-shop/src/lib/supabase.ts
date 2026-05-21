import { createClient, type SupabaseClient } from "@supabase/supabase-js";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";
const serviceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY ?? "";

/**
 * Service-Role-Client — VOLLZUGRIFF auf die DB.
 * Nur in Server-Code verwenden (API-Routen, Server-Components).
 * Wir cachen die Instanz pro Worker.
 */
let serviceClient: SupabaseClient | null = null;
export function supabaseAdmin(): SupabaseClient {
  if (!serviceClient) {
    serviceClient = createClient(supabaseUrl, serviceRoleKey, {
      auth: { persistSession: false, autoRefreshToken: false },
    });
  }
  return serviceClient;
}

/** Optionaler Anon-Client für Public-Reads (aktuell nicht verwendet). */
export function supabasePublic(): SupabaseClient {
  return createClient(supabaseUrl, anonKey, {
    auth: { persistSession: false },
  });
}

export const EBOOKS_BUCKET = "ebooks";

/**
 * Erstellt eine signierte Download-URL für eine PDF im Storage.
 * Default: 7 Tage Gültigkeit (Kunden bekommen sie per E-Mail).
 */
export async function createSignedDownload(
  storagePath: string,
  expiresIn = 60 * 60 * 24 * 7,
): Promise<string | null> {
  const { data, error } = await supabaseAdmin()
    .storage.from(EBOOKS_BUCKET)
    .createSignedUrl(storagePath, expiresIn, { download: true });
  if (error) {
    console.error("[supabase] createSignedUrl failed", error);
    return null;
  }
  return data.signedUrl;
}
