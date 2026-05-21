import { Resend } from "resend";
import { formatPriceCHF } from "@/lib/utils";

let _resend: Resend | null = null;
function getResend(): Resend {
  if (!_resend) {
    const key = process.env.RESEND_API_KEY;
    if (!key) throw new Error("RESEND_API_KEY nicht gesetzt");
    _resend = new Resend(key);
  }
  return _resend;
}

interface OrderItemEmail {
  title: string;
  quantity: number;
  unitPriceChf: number;
  downloadUrl: string | null;
}

interface OrderEmailParams {
  to: string;
  customerName?: string | null;
  orderId: string;
  totalChf: number;
  items: OrderItemEmail[];
}

/**
 * Bestellbestätigung mit Download-Links. Wird vom Stripe-Webhook
 * nach erfolgreicher Zahlung getriggert.
 *
 * Falls für ein Produkt noch keine PDF hochgeladen wurde (Admin hat
 * Upload vergessen), zeigen wir im Email den Hinweis dass wir es
 * manuell nachsenden — kein gebrochener Link.
 */
export async function sendOrderConfirmation(params: OrderEmailParams) {
  const from = process.env.RESEND_FROM_EMAIL ?? "SwissMoments <noreply@swissmoments.ch>";

  const itemsHtml = params.items
    .map((item) => {
      const linkBlock = item.downloadUrl
        ? `<a href="${item.downloadUrl}" style="display:inline-block;margin-top:8px;padding:10px 18px;background:#C8102E;color:#fff;text-decoration:none;border-radius:999px;font-weight:600;">PDF herunterladen</a>`
        : `<p style="margin:8px 0 0;color:#888;font-size:13px;">Wir senden dir den Download-Link manuell in den nächsten Stunden. Danke für deine Geduld!</p>`;
      return `
        <tr>
          <td style="padding:14px 0;border-bottom:1px solid #eee;">
            <p style="margin:0;font-family:Georgia,serif;font-size:17px;color:#2C2C2C;">${escapeHtml(item.title)}</p>
            <p style="margin:4px 0 0;color:#666;font-size:13px;">${item.quantity}× · ${formatPriceCHF(item.unitPriceChf)}</p>
            ${linkBlock}
          </td>
        </tr>`;
    })
    .join("");

  const subject = `Deine SwissMoments Bestellung #${params.orderId.slice(0, 8)}`;

  const html = `
  <!doctype html>
  <html><body style="margin:0;padding:24px;background:#F8F1E3;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;color:#2C2C2C;">
    <table width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;margin:0 auto;background:#fff;border-radius:16px;overflow:hidden;">
      <tr><td style="padding:32px 32px 16px;">
        <p style="margin:0;font-family:Georgia,serif;font-size:28px;"><span style="color:#C8102E;">Swiss</span>Moments</p>
      </td></tr>
      <tr><td style="padding:0 32px 8px;">
        <h1 style="margin:0;font-family:Georgia,serif;font-size:24px;color:#2C2C2C;">Vielen Dank${params.customerName ? `, ${escapeHtml(params.customerName)}` : ""}!</h1>
        <p style="color:#666;font-size:15px;line-height:1.5;">Deine Bestellung ist bei uns angekommen und du kannst deine E-Books unten direkt herunterladen. Die Links sind 7 Tage gültig.</p>
      </td></tr>
      <tr><td style="padding:0 32px;">
        <table width="100%" cellpadding="0" cellspacing="0">${itemsHtml}</table>
      </td></tr>
      <tr><td style="padding:18px 32px;border-top:1px solid #eee;">
        <p style="margin:0;display:flex;justify-content:space-between;font-size:15px;">
          <span style="color:#666;">Gesamt</span>
          <strong style="font-family:Georgia,serif;font-size:18px;color:#C8102E;">${formatPriceCHF(params.totalChf)}</strong>
        </p>
        <p style="margin:8px 0 0;color:#999;font-size:12px;">Bestellnummer: ${params.orderId}</p>
      </td></tr>
      <tr><td style="padding:24px 32px 32px;color:#999;font-size:12px;line-height:1.5;">
        Brauchst du Hilfe? Antworte einfach auf diese E-Mail — wir antworten meistens innert 24 Stunden.<br/>
        Mit ❤️ aus der Schweiz · <a href="https://swissmoments.ch" style="color:#C8102E;">swissmoments.ch</a>
      </td></tr>
    </table>
  </body></html>`;

  const { error } = await getResend().emails.send({
    from,
    to: params.to,
    subject,
    html,
    replyTo: "hallo@swissmoments.ch",
  });

  if (error) {
    console.error("[resend] sendOrderConfirmation failed", error);
    throw error;
  }
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
