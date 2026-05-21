import Link from "next/link";
import { Button } from "@/components/ui/button";

export default function OrderCancelPage() {
  return (
    <div className="container max-w-xl py-20 text-center">
      <h1 className="font-serif text-3xl text-brand-ink md:text-4xl">
        Bestellung abgebrochen
      </h1>
      <p className="mt-3 text-brand-ink/70">
        Kein Problem — dein Warenkorb ist noch da. Du kannst den Checkout
        jederzeit neu starten.
      </p>
      <div className="mt-7 flex flex-wrap justify-center gap-3">
        <Button asChild>
          <Link href="/shop">Weiter shoppen</Link>
        </Button>
        <Button asChild variant="outline">
          <Link href="/">Zur Startseite</Link>
        </Button>
      </div>
    </div>
  );
}
