import Link from "next/link";
import { redirect } from "next/navigation";
import { isAdmin } from "@/lib/admin-auth";

export const dynamic = "force-dynamic";

export default async function AuthedAdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  if (!(await isAdmin())) redirect("/admin/login");

  return (
    <div className="min-h-screen bg-brand-cream">
      <nav className="border-b border-brand-ink/10 bg-white/70 backdrop-blur">
        <div className="container flex h-16 items-center justify-between">
          <div className="flex items-center gap-6">
            <Link href="/admin" className="font-serif text-lg text-brand-ink">
              <span className="text-brand-red">Swiss</span>Moments Admin
            </Link>
            <Link
              href="/admin"
              className="text-sm text-brand-ink/70 hover:text-brand-red"
            >
              Dashboard
            </Link>
            <Link
              href="/admin/orders"
              className="text-sm text-brand-ink/70 hover:text-brand-red"
            >
              Bestellungen
            </Link>
            <Link
              href="/admin/products"
              className="text-sm text-brand-ink/70 hover:text-brand-red"
            >
              PDFs
            </Link>
          </div>
          <form action="/api/admin/logout" method="post">
            <button
              type="submit"
              className="text-sm text-brand-ink/60 hover:text-brand-red"
            >
              Abmelden
            </button>
          </form>
        </div>
      </nav>
      <main className="container py-10">{children}</main>
    </div>
  );
}
