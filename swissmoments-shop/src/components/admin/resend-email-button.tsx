"use client";

import { useState } from "react";
import { Mail } from "lucide-react";
import { Button } from "@/components/ui/button";

export function ResendEmailButton({ orderId }: { orderId: string }) {
  const [status, setStatus] = useState<"idle" | "loading" | "ok" | "error">(
    "idle",
  );

  async function handle() {
    setStatus("loading");
    const res = await fetch("/api/admin/resend-email", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ orderId }),
    });
    setStatus(res.ok ? "ok" : "error");
    setTimeout(() => setStatus("idle"), 3000);
  }

  return (
    <Button
      size="sm"
      variant={status === "ok" ? "gold" : "outline"}
      onClick={handle}
      disabled={status === "loading"}
    >
      <Mail className="h-4 w-4" />
      {status === "loading" && "Sende…"}
      {status === "idle" && "Email neu senden"}
      {status === "ok" && "Verschickt!"}
      {status === "error" && "Fehler — nochmal?"}
    </Button>
  );
}
