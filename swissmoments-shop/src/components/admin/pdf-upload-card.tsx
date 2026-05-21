"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Check, FileUp, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";

interface Props {
  slug: string;
  title: string;
  decade: string;
  currentFilename: string | null;
  currentSize: number | null;
  updatedAt: string | null;
}

export function PdfUploadCard({
  slug,
  title,
  decade,
  currentFilename,
  currentSize,
  updatedAt,
}: Props) {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [status, setStatus] = useState<"idle" | "uploading" | "ok" | "error">(
    "idle",
  );
  const [error, setError] = useState<string | null>(null);

  async function handleFile(file: File) {
    setStatus("uploading");
    setError(null);

    const fd = new FormData();
    fd.append("slug", slug);
    fd.append("file", file);

    const res = await fetch("/api/admin/upload", { method: "POST", body: fd });
    if (res.ok) {
      setStatus("ok");
      router.refresh();
      setTimeout(() => setStatus("idle"), 2500);
    } else {
      const data = await res.json().catch(() => ({}));
      setError(data?.error ?? "Upload fehlgeschlagen");
      setStatus("error");
    }
  }

  const hasFile = !!currentFilename;

  return (
    <div className="rounded-2xl bg-white p-5 ring-1 ring-brand-ink/5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-serif text-lg text-brand-ink">{title}</p>
          <p className="text-xs uppercase tracking-wider text-brand-ink/55">
            {decade} · {slug}
          </p>
        </div>
        {hasFile ? (
          <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-medium text-emerald-700">
            <Check className="h-3 w-3" />
            Bereit
          </span>
        ) : (
          <span className="inline-flex items-center rounded-full bg-brand-gold/15 px-2.5 py-1 text-xs font-medium text-brand-ink">
            Fehlt
          </span>
        )}
      </div>

      {hasFile && (
        <div className="mt-3 rounded-lg bg-brand-cream/40 px-3 py-2 text-xs text-brand-ink/65">
          <p className="truncate">{currentFilename}</p>
          <p>
            {currentSize ? `${(currentSize / 1024 / 1024).toFixed(2)} MB` : ""}
            {updatedAt &&
              ` · zuletzt aktualisiert ${new Date(updatedAt).toLocaleDateString("de-CH")}`}
          </p>
        </div>
      )}

      {error && <p className="mt-3 text-xs text-brand-red">{error}</p>}

      <input
        ref={inputRef}
        type="file"
        accept="application/pdf"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) handleFile(file);
          e.target.value = "";
        }}
      />

      <div className="mt-4 flex justify-end">
        <Button
          size="sm"
          variant={hasFile ? "outline" : "default"}
          onClick={() => inputRef.current?.click()}
          disabled={status === "uploading"}
        >
          {status === "uploading" ? (
            <>
              <RefreshCw className="h-4 w-4 animate-spin" />
              Wird hochgeladen…
            </>
          ) : status === "ok" ? (
            <>
              <Check className="h-4 w-4" />
              Hochgeladen
            </>
          ) : (
            <>
              <FileUp className="h-4 w-4" />
              {hasFile ? "Ersetzen" : "PDF hochladen"}
            </>
          )}
        </Button>
      </div>
    </div>
  );
}
