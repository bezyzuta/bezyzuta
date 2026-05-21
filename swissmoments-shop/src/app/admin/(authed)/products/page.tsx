import { supabaseAdmin } from "@/lib/supabase";
import { products } from "@/lib/products";
import { PdfUploadCard } from "@/components/admin/pdf-upload-card";

export const dynamic = "force-dynamic";

export default async function AdminProductsPage() {
  const supabase = supabaseAdmin();
  const { data: files } = await supabase
    .from("products_files")
    .select("slug, filename, size_bytes, updated_at");

  const filesBySlug = new Map(
    (files ?? []).map((f) => [f.slug, f] as const),
  );

  return (
    <div>
      <h1 className="font-serif text-3xl text-brand-ink">PDFs verwalten</h1>
      <p className="mt-1 text-sm text-brand-ink/60">
        Pro Produkt eine PDF hochladen. Nach erfolgreichem Kauf bekommt der
        Kunde einen 7-Tage-gültigen Download-Link aus dem Storage.
      </p>

      <div className="mt-8 grid gap-4 md:grid-cols-2">
        {products.map((p) => (
          <PdfUploadCard
            key={p.slug}
            slug={p.slug}
            title={p.title}
            decade={p.decade}
            currentFilename={filesBySlug.get(p.slug)?.filename ?? null}
            currentSize={filesBySlug.get(p.slug)?.size_bytes ?? null}
            updatedAt={filesBySlug.get(p.slug)?.updated_at ?? null}
          />
        ))}
      </div>
    </div>
  );
}
