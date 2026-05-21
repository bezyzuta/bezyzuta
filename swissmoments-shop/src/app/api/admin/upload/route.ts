import { NextResponse } from "next/server";
import { isAdmin } from "@/lib/admin-auth";
import { supabaseAdmin, EBOOKS_BUCKET } from "@/lib/supabase";
import { getProductBySlug } from "@/lib/products";

export const runtime = "nodejs";

/**
 * POST /api/admin/upload
 *
 * multipart/form-data:
 *   - slug (string)
 *   - file (PDF)
 *
 * Lädt die PDF nach Supabase Storage (`ebooks/<slug>.pdf`) und upsertet
 * den Eintrag in `products_files`.
 */
export async function POST(req: Request) {
  if (!(await isAdmin())) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const form = await req.formData();
  const slug = form.get("slug");
  const file = form.get("file");

  if (typeof slug !== "string" || !slug) {
    return NextResponse.json({ error: "Slug fehlt" }, { status: 400 });
  }
  if (!(file instanceof File)) {
    return NextResponse.json({ error: "Datei fehlt" }, { status: 400 });
  }
  if (!getProductBySlug(slug)) {
    return NextResponse.json(
      { error: `Unbekannter Produkt-Slug: ${slug}` },
      { status: 400 },
    );
  }
  if (file.size > 200 * 1024 * 1024) {
    return NextResponse.json(
      { error: "Datei ist grösser als 200 MB" },
      { status: 400 },
    );
  }

  const supabase = supabaseAdmin();
  const storagePath = `${slug}.pdf`;
  const arrayBuffer = await file.arrayBuffer();

  const { error: uploadErr } = await supabase.storage
    .from(EBOOKS_BUCKET)
    .upload(storagePath, arrayBuffer, {
      contentType: "application/pdf",
      upsert: true,
    });
  if (uploadErr) {
    console.error("[upload] storage error", uploadErr);
    return NextResponse.json(
      { error: `Storage-Upload fehlgeschlagen: ${uploadErr.message}` },
      { status: 500 },
    );
  }

  const { error: rowErr } = await supabase.from("products_files").upsert({
    slug,
    storage_path: storagePath,
    filename: file.name,
    size_bytes: file.size,
    updated_at: new Date().toISOString(),
  });
  if (rowErr) {
    return NextResponse.json({ error: rowErr.message }, { status: 500 });
  }

  return NextResponse.json({ ok: true, storage_path: storagePath });
}
