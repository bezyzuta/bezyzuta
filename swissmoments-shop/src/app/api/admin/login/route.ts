import { NextResponse } from "next/server";
import { setAdminCookie, verifyPassword } from "@/lib/admin-auth";

export const runtime = "nodejs";

export async function POST(req: Request) {
  const { password } = (await req.json()) as { password?: string };
  if (!password || !verifyPassword(password)) {
    return NextResponse.json({ error: "Falsches Passwort" }, { status: 401 });
  }
  await setAdminCookie();
  return NextResponse.json({ ok: true });
}
