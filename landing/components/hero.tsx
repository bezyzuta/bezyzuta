"use client";

import { motion } from "framer-motion";
import { ArrowRight, Sparkles, Play } from "lucide-react";
import { Button } from "@/components/ui/button";

export function Hero() {
  return (
    <section className="relative min-h-screen flex items-center justify-center px-6 pt-24 pb-16 overflow-hidden">
      {/* Ambient gradient orbs */}
      <div className="absolute inset-0 -z-10 pointer-events-none">
        <motion.div
          initial={{ opacity: 0, scale: 0.8 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 2, ease: "easeOut" }}
          className="absolute top-[10%] left-[15%] w-[600px] h-[600px] rounded-full bg-purple-600/25 blur-[140px]"
        />
        <motion.div
          initial={{ opacity: 0, scale: 0.8 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 2, delay: 0.3, ease: "easeOut" }}
          className="absolute bottom-[10%] right-[10%] w-[500px] h-[500px] rounded-full bg-cyan-500/20 blur-[140px]"
        />
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 2, delay: 0.6 }}
          className="absolute top-[40%] left-[50%] -translate-x-1/2 w-[800px] h-[300px] rounded-full bg-violet-500/10 blur-[120px]"
        />
      </div>

      {/* Grid background with radial fade */}
      <div className="absolute inset-0 -z-10 bg-grid mask-radial-fade opacity-40" />

      {/* Top nav-like brand mark */}
      <div className="absolute top-0 left-0 right-0 z-10 px-6 py-6">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="relative w-7 h-7 rounded-md bg-gradient-to-br from-purple-500 to-cyan-500 shadow-[0_0_20px_-2px_rgba(168,85,247,0.5)]">
              <div className="absolute inset-[2px] rounded bg-[#07070c] flex items-center justify-center">
                <Sparkles className="w-3 h-3 text-purple-300" />
              </div>
            </div>
            <span className="font-semibold tracking-tight text-zinc-100">
              ClipForge
            </span>
          </div>
          <Button variant="ghost" size="sm">
            Login
          </Button>
        </div>
      </div>

      <div className="relative max-w-5xl mx-auto text-center">
        {/* Pill badge */}
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
          className="inline-flex items-center gap-2 px-3.5 py-1.5 mb-8 rounded-full border border-purple-500/20 bg-purple-500/[0.06] backdrop-blur-sm"
        >
          <span className="relative flex h-1.5 w-1.5">
            <span className="absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75 animate-ping" />
            <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-cyan-400" />
          </span>
          <span className="text-xs font-medium text-purple-200 tracking-wide">
            KI-powered Shorts-Pipeline · Beta
          </span>
        </motion.div>

        {/* Headline */}
        <motion.h1
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.1, ease: [0.16, 1, 0.3, 1] }}
          className="text-5xl sm:text-6xl md:text-7xl lg:text-[5.5rem] font-bold tracking-[-0.03em] leading-[0.95] mb-7 text-balance"
        >
          <span className="bg-gradient-to-b from-white via-zinc-100 to-zinc-400 bg-clip-text text-transparent">
            Lange Videos.
          </span>
          <br />
          <span className="bg-gradient-to-r from-purple-400 via-fuchsia-400 to-cyan-400 bg-clip-text text-transparent">
            Virale Shorts.
          </span>
        </motion.h1>

        {/* Subheadline */}
        <motion.p
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.2 }}
          className="text-base sm:text-lg md:text-xl text-zinc-400 max-w-2xl mx-auto mb-10 leading-relaxed text-balance"
        >
          Lade ein Video hoch — ClipForge findet die viralsten Momente,
          schneidet, captioned und exportiert YouTube-ready Shorts. Kein
          Editor-Bullshit. Keine 8 Stunden Schnittarbeit. Nur Ergebnisse.
        </motion.p>

        {/* CTAs */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.3 }}
          className="flex flex-col sm:flex-row items-center justify-center gap-3 mb-6"
        >
          <Button size="lg" className="w-full sm:w-auto">
            Jetzt kostenlos testen
            <ArrowRight className="w-4 h-4" />
          </Button>
          <Button size="lg" variant="outline" className="w-full sm:w-auto">
            <Play className="w-3.5 h-3.5" />
            Demo ansehen
          </Button>
        </motion.div>

        {/* Trust line */}
        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.8, delay: 0.5 }}
          className="text-xs text-zinc-500"
        >
          Keine Kreditkarte erforderlich · Erstes Short in unter 2 Minuten
        </motion.p>

        {/* Mock preview surface */}
        <motion.div
          initial={{ opacity: 0, y: 60, scale: 0.95 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{
            duration: 1.2,
            delay: 0.6,
            ease: [0.16, 1, 0.3, 1],
          }}
          className="relative mt-20 mx-auto max-w-4xl"
        >
          {/* Gradient border wrap */}
          <div className="relative rounded-2xl p-[1px] bg-gradient-to-b from-white/[0.12] via-white/[0.04] to-transparent">
            <div className="rounded-2xl bg-[#0a0a12] overflow-hidden">
              {/* Window chrome */}
              <div className="flex items-center gap-2 px-4 py-3 border-b border-white/[0.06]">
                <div className="flex gap-1.5">
                  <div className="w-2.5 h-2.5 rounded-full bg-zinc-700" />
                  <div className="w-2.5 h-2.5 rounded-full bg-zinc-700" />
                  <div className="w-2.5 h-2.5 rounded-full bg-zinc-700" />
                </div>
                <div className="flex-1 flex justify-center">
                  <div className="px-3 py-1 rounded-md bg-white/[0.03] text-[10px] text-zinc-500 font-mono">
                    clipforge.app/studio
                  </div>
                </div>
              </div>

              {/* Studio interior */}
              <div className="grid grid-cols-12 gap-3 p-4">
                {/* Left: source video timeline */}
                <div className="col-span-8 space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-[11px] text-zinc-500 uppercase tracking-wider">
                      Source · 78 min
                    </span>
                    <span className="text-[11px] text-cyan-400 font-mono">
                      ● analysiert
                    </span>
                  </div>
                  <div className="relative h-14 rounded-lg bg-gradient-to-r from-zinc-900 to-zinc-900/50 border border-white/5 overflow-hidden">
                    {/* waveform-ish bars */}
                    <div className="absolute inset-0 flex items-center px-2 gap-[2px]">
                      {Array.from({ length: 80 }).map((_, i) => (
                        <div
                          key={i}
                          className="flex-1 bg-zinc-600/40 rounded-sm"
                          style={{
                            height: `${20 + Math.sin(i * 0.5) * 15 + Math.cos(i * 0.3) * 10}%`,
                          }}
                        />
                      ))}
                    </div>
                    {/* viral moment highlights */}
                    {[15, 42, 68].map((pos, i) => (
                      <motion.div
                        key={i}
                        initial={{ opacity: 0, scaleY: 0.5 }}
                        animate={{ opacity: 1, scaleY: 1 }}
                        transition={{ delay: 1.2 + i * 0.2, duration: 0.5 }}
                        className="absolute top-0 bottom-0 bg-gradient-to-b from-purple-500/30 to-cyan-500/30 border-x border-purple-400/60 rounded-sm"
                        style={{ left: `${pos}%`, width: "8%" }}
                      />
                    ))}
                  </div>
                  <div className="grid grid-cols-3 gap-2">
                    {[
                      { label: "00:15 – 00:42", score: "94" },
                      { label: "12:08 – 12:39", score: "89" },
                      { label: "54:21 – 54:55", score: "92" },
                    ].map((clip, i) => (
                      <motion.div
                        key={i}
                        initial={{ opacity: 0, y: 8 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: 1.5 + i * 0.1 }}
                        className="p-2.5 rounded-md bg-white/[0.02] border border-white/[0.06] hover:border-purple-500/30 transition-colors"
                      >
                        <div className="text-[10px] text-zinc-500 font-mono mb-1">
                          {clip.label}
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-xs text-zinc-300">
                            Clip {i + 1}
                          </span>
                          <span className="text-[10px] text-cyan-400 font-mono">
                            ★ {clip.score}
                          </span>
                        </div>
                      </motion.div>
                    ))}
                  </div>
                </div>

                {/* Right: 9:16 preview */}
                <div className="col-span-4">
                  <div className="aspect-[9/16] rounded-lg relative overflow-hidden bg-gradient-to-br from-purple-900/40 via-zinc-900 to-cyan-900/30 border border-white/[0.08]">
                    <div className="absolute inset-0 bg-dots opacity-50" />
                    <div className="absolute top-3 left-3 right-3">
                      <div className="px-2 py-1 rounded bg-black/40 backdrop-blur-sm">
                        <div className="text-[9px] text-white font-bold tracking-wide">
                          POV: NIEMAND HAT DAMIT
                          <br />
                          GERECHNET 🤯
                        </div>
                      </div>
                    </div>
                    <div className="absolute bottom-0 left-0 right-0 p-3">
                      <motion.div
                        initial={{ width: "0%" }}
                        animate={{ width: "100%" }}
                        transition={{
                          duration: 8,
                          delay: 2,
                          repeat: Infinity,
                          ease: "linear",
                        }}
                        className="h-0.5 bg-gradient-to-r from-purple-400 to-cyan-400 rounded-full mb-2"
                      />
                      <div className="text-[10px] text-white font-bold text-center">
                        <span className="bg-cyan-400/90 text-black px-1 rounded">
                          und
                        </span>{" "}
                        <span className="text-white/70">dann passierte</span>
                      </div>
                    </div>
                    <motion.div
                      animate={{ opacity: [0.5, 1, 0.5] }}
                      transition={{ duration: 2, repeat: Infinity }}
                      className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-10 h-10 rounded-full bg-white/10 backdrop-blur-sm border border-white/20 flex items-center justify-center"
                    >
                      <Play className="w-4 h-4 text-white fill-white" />
                    </motion.div>
                  </div>
                </div>
              </div>
            </div>
          </div>
          {/* Glow underneath */}
          <div className="absolute -bottom-20 left-1/2 -translate-x-1/2 w-3/4 h-32 bg-purple-500/20 blur-[80px] -z-10" />
        </motion.div>
      </div>
    </section>
  );
}
