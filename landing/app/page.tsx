import { Hero } from "@/components/hero";
import { Features } from "@/components/features";

export default function Home() {
  return (
    <main className="relative min-h-screen overflow-hidden">
      <Hero />
      <Features />
    </main>
  );
}
