import { cookies } from "next/headers";
import { createHmac, timingSafeEqual } from "crypto";

/**
 * Sehr schlankes Admin-Auth für eine einzelne Person.
 *
 * Login: User schickt Passwort, wir vergleichen mit env.ADMIN_PASSWORD.
 * Bei Erfolg setzen wir den Cookie `sm_admin` auf HMAC(SESSION_SECRET, "admin").
 * Jede Admin-Seite/API ruft `requireAdmin()` auf — schlägt der Cookie-HMAC
 * fehl, redirecten / 401.
 *
 * Kein User-Management, keine DB-Tabelle — einfach und sicher genug für
 * einen Single-Operator-Shop.
 */

const COOKIE_NAME = "sm_admin";
const COOKIE_MAX_AGE = 60 * 60 * 24 * 30; // 30 Tage

function sessionSecret(): string {
  const s = process.env.SESSION_SECRET;
  if (!s || s.length < 32) {
    throw new Error("SESSION_SECRET fehlt oder zu kurz (min. 32 Zeichen).");
  }
  return s;
}

function expectedToken(): string {
  return createHmac("sha256", sessionSecret()).update("admin").digest("hex");
}

export function verifyPassword(input: string): boolean {
  const expected = process.env.ADMIN_PASSWORD ?? "";
  if (!expected || expected === "changeMeNow!2026") {
    // Vergessen zu setzen → besser explizit ablehnen statt Default zuzulassen.
    return false;
  }
  const a = Buffer.from(input);
  const b = Buffer.from(expected);
  if (a.length !== b.length) return false;
  return timingSafeEqual(a, b);
}

export async function setAdminCookie() {
  const jar = await cookies();
  jar.set(COOKIE_NAME, expectedToken(), {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: COOKIE_MAX_AGE,
  });
}

export async function clearAdminCookie() {
  const jar = await cookies();
  jar.delete(COOKIE_NAME);
}

export async function isAdmin(): Promise<boolean> {
  const jar = await cookies();
  const got = jar.get(COOKIE_NAME)?.value;
  if (!got) return false;
  const expected = expectedToken();
  if (got.length !== expected.length) return false;
  return timingSafeEqual(Buffer.from(got), Buffer.from(expected));
}
