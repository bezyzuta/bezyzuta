import { Hero } from "@/components/hero";
import { FeaturedProducts } from "@/components/featured-products";
import { AboutSection } from "@/components/about-section";
import { Testimonials } from "@/components/testimonials";

export default function HomePage() {
  return (
    <>
      <Hero />
      <FeaturedProducts />
      <AboutSection />
      <Testimonials />
    </>
  );
}
