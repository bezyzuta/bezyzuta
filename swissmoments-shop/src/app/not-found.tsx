import Link from "next/link";
import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <div className="container flex min-h-[60vh] flex-col items-center justify-center py-20 text-center">
      <p className="font-serif text-7xl text-brand-red md:text-8xl">404</p>
      <h1 className="mt-4 font-serif text-3xl text-brand-ink md:text-4xl">
        Hier ist nichts mehr aus der guten alten Zeit.
      </h1>
      <p className="mt-3 max-w-md text-brand-ink/70">
        Die Seite, die du suchst, gibt es nicht oder wurde verschoben.
      </p>
      <Button asChild className="mt-7">
        <Link href="/">Zurück zur Startseite</Link>
      </Button>
    </div>
  );
}
