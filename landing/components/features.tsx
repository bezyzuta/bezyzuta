"use client";

import { motion } from "framer-motion";
import {
  Wand2,
  Scissors,
  SlidersHorizontal,
  Captions,
  ImageIcon,
  Flame,
  Mic,
  Rocket,
  type LucideIcon,
} from "lucide-react";

type Feature = {
  icon: LucideIcon;
  title: string;
  description: string;
  accent: "purple" | "cyan" | "fuchsia" | "violet";
};

const features: Feature[] = [
  {
    icon: Wand2,
    title: "AI Skript-Generator",
    description:
      "Sag was du willst — bekomm ein virales Skript. Hook, Storyline, CTA. Tonfall pro Nische einstellbar.",
    accent: "purple",
  },
  {
    icon: Scissors,
    title: "Auto Video-Clipper",
    description:
      "Lade ein 60-Min-Video hoch, bekomm 10 Clips mit den viralsten Momenten. KI findet sie via Voll-Transkript-Analyse.",
    accent: "cyan",
  },
  {
    icon: SlidersHorizontal,
    title: "Manueller Editor",
    description:
      "Wenn du Kontrolle willst: Frame-genaue Timeline, Cuts setzen, Reframe verschieben, alles in einem Interface.",
    accent: "violet",
  },
  {
    icon: Captions,
    title: "Live-Captions",
    description:
      "TikTok-Style Karaoke-Captions, animiert. Word-by-word Highlights, eigene Farben, pop-in Animationen.",
    accent: "fuchsia",
  },
  {
    icon: ImageIcon,
    title: "KI Thumbnail-Generator",
    description:
      "Klickstarke Thumbnails aus deinem Clip. Mehrere Stile pro Nische, Text-Overlays, sofort einsatzbereit.",
    accent: "purple",
  },
  {
    icon: Flame,
    title: "Nischen-Trend-Engine",
    description:
      "Templates für Roblox, Gaming, Motivation, Facts, Podcast-Clips. Pro Nische optimierte Hooks und Cuts.",
    accent: "cyan",
  },
  {
    icon: Mic,
    title: "AI Voiceover",
    description:
      "ElevenLabs-Quality Stimmen in 30+ Sprachen. Multilingual, emotional, mit Smart-Timing zum Video synchronisiert.",
    accent: "violet",
  },
  {
    icon: Rocket,
    title: "1-Klick Export",
    description:
      "9:16, optimiert für YouTube Shorts, TikTok und Reels. Render in unter 60 Sekunden, sofort hochlade-bereit.",
    accent: "fuchsia",
  },
];

const accentMap: Record<Feature["accent"], string> = {
  purple: "from-purple-500/20 to-purple-500/0 text-purple-300 border-purple-500/20",
  cyan: "from-cyan-500/20 to-cyan-500/0 text-cyan-300 border-cyan-500/20",
  violet: "from-violet-500/20 to-violet-500/0 text-violet-300 border-violet-500/20",
  fuchsia: "from-fuchsia-500/20 to-fuchsia-500/0 text-fuchsia-300 border-fuchsia-500/20",
};

const hoverGlowMap: Record<Feature["accent"], string> = {
  purple: "group-hover:shadow-[0_0_40px_-12px_rgba(168,85,247,0.4)]",
  cyan: "group-hover:shadow-[0_0_40px_-12px_rgba(6,182,212,0.4)]",
  violet: "group-hover:shadow-[0_0_40px_-12px_rgba(139,92,246,0.4)]",
  fuchsia: "group-hover:shadow-[0_0_40px_-12px_rgba(217,70,239,0.4)]",
};

export function Features() {
  return (
    <section className="relative py-32 px-6 overflow-hidden">
      {/* Background accent */}
      <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[800px] h-[400px] bg-purple-600/10 blur-[120px] -z-10 pointer-events-none" />
      <div className="absolute inset-0 -z-10 bg-dots opacity-30 mask-radial-fade pointer-events-none" />

      <div className="relative max-w-7xl mx-auto">
        {/* Section header */}
        <div className="text-center mb-20 max-w-3xl mx-auto">
          <motion.span
            initial={{ opacity: 0, y: 10 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.5 }}
            className="inline-block px-3 py-1 mb-5 text-xs font-medium tracking-wider uppercase text-cyan-400 border border-cyan-500/20 rounded-full bg-cyan-500/[0.04]"
          >
            Features
          </motion.span>
          <motion.h2
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.6 }}
            className="text-4xl sm:text-5xl md:text-6xl font-bold tracking-[-0.02em] leading-[1.05] mb-6 text-balance"
          >
            <span className="bg-gradient-to-br from-white via-zinc-100 to-zinc-500 bg-clip-text text-transparent">
              Alles was du brauchst.
              <br />
              Nichts was nervt.
            </span>
          </motion.h2>
          <motion.p
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.6, delay: 0.1 }}
            className="text-base sm:text-lg text-zinc-400 leading-relaxed text-balance"
          >
            Acht Werkzeuge, ein Workflow. Null Friktion zwischen Idee und
            veröffentlichtem Short.
          </motion.p>
        </div>

        {/* Feature grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {features.map((feature, i) => {
            const Icon = feature.icon;
            return (
              <motion.div
                key={feature.title}
                initial={{ opacity: 0, y: 24 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, margin: "-80px" }}
                transition={{
                  duration: 0.5,
                  delay: i * 0.06,
                  ease: [0.16, 1, 0.3, 1],
                }}
                className={`group relative rounded-2xl p-[1px] bg-gradient-to-b from-white/[0.08] to-white/[0.02] transition-all duration-500 ${hoverGlowMap[feature.accent]}`}
              >
                <div className="relative h-full rounded-2xl bg-[#0a0a12] p-6 overflow-hidden">
                  {/* Hover gradient wash */}
                  <div
                    className={`absolute inset-0 rounded-2xl opacity-0 group-hover:opacity-100 transition-opacity duration-500 bg-gradient-to-br ${accentMap[feature.accent]}`}
                  />

                  <div className="relative">
                    {/* Icon */}
                    <div
                      className={`inline-flex items-center justify-center w-11 h-11 rounded-xl border bg-gradient-to-br ${accentMap[feature.accent]} mb-5`}
                    >
                      <Icon className="w-5 h-5" strokeWidth={1.75} />
                    </div>

                    {/* Title */}
                    <h3 className="text-base font-semibold text-zinc-100 mb-2 tracking-tight">
                      {feature.title}
                    </h3>

                    {/* Description */}
                    <p className="text-sm text-zinc-400 leading-relaxed">
                      {feature.description}
                    </p>
                  </div>
                </div>
              </motion.div>
            );
          })}
        </div>

        {/* Closing line */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.6, delay: 0.2 }}
          className="mt-24 text-center"
        >
          <p className="text-sm text-zinc-500">
            Built für Creators die schneller wachsen wollen — ohne Editor-Skills,
            ohne Vollzeit-Team.
          </p>
        </motion.div>
      </div>
    </section>
  );
}
