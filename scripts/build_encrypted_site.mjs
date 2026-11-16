import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.dirname(__dirname);
const outDir = path.join(root, "_site");
const outDataDir = path.join(outDir, "data");
fs.mkdirSync(outDataDir, { recursive: true });

const KEY_HEX = "9f3c8a1e7b24d065a8e1c43f5d902b7e61a4c8d20e3f7b95a1c6d4e802b3f791";
const key = Buffer.from(KEY_HEX, "hex");

function encryptBuffer(buf) {
  const iv = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv("aes-256-gcm", key, iv);
  const ct = Buffer.concat([cipher.update(buf), cipher.final(), cipher.getAuthTag()]);
  return JSON.stringify({ v: 1, iv: iv.toString("base64"), d: ct.toString("base64") });
}

// 1. Encrypt booster_data.json -> _site/data/booster_data.enc
const dataJson = fs.readFileSync(path.join(root, "data", "booster_data.json"));
fs.writeFileSync(path.join(outDataDir, "booster_data.enc"), encryptBuffer(dataJson));

// 2. Extract body markup (excluding app.js script tag) and encrypt -> _site/data/shell.enc
const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
const bodyMatch = html.match(/<body>([\s\S]*?)<script\s+src="app\.js[^"]*"><\/script>[\s\S]*?<\/body>/i);
if (!bodyMatch) {
  throw new Error("Gagal mengekstrak <body> dari index.html");
}
const shellMarkup = bodyMatch[1].trim();
fs.writeFileSync(path.join(outDataDir, "shell.enc"), encryptBuffer(Buffer.from(shellMarkup, "utf8")));

// 3. Write minimal loader index.html
const loaderHtml = `<!DOCTYPE html>
<html lang="id" data-theme="light">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self';" />
  <title>Q3 Booster Up — Monitoring Paket</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@500;600&display=swap" rel="stylesheet" />
  <link rel="stylesheet" href="styles.css?v=20261116a" />
</head>
<body>
  <div id="appRoot" style="padding:32px;font-family:Inter,system-ui,sans-serif;color:#475569;font-size:14px">Memuat dashboard...</div>
  <script src="loader.js?v=20261116c"></script>
</body>
</html>
`;
fs.writeFileSync(path.join(outDir, "index.html"), loaderHtml, "utf8");

// 4. Write loader.js
const loaderJs = `(() => {
  const K = "9f3c8a1e7b24d065a8e1c43f5d902b7e61a4c8d20e3f7b95a1c6d4e802b3f791";
  const b64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
  const hex = (h) => new Uint8Array(h.match(/../g).map((x) => parseInt(x, 16)));
  (async () => {
    try {
      const res = await fetch("./data/shell.enc?t=" + Date.now(), { cache: "no-store" });
      if (!res.ok) throw new Error("HTTP " + res.status);
      const enc = await res.json();
      const key = await crypto.subtle.importKey("raw", hex(K), "AES-GCM", false, ["decrypt"]);
      const dec = await crypto.subtle.decrypt({ name: "AES-GCM", iv: b64(enc.iv) }, key, b64(enc.d));
      document.body.innerHTML = new TextDecoder().decode(dec);
      const s = document.createElement("script");
      s.src = "app.js?v=20261116c";
      document.body.appendChild(s);
    } catch (e) {
      const root = document.getElementById("appRoot");
      if (root) root.textContent = "Gagal memuat halaman: " + (e?.message || e);
    }
  })();
})();
`;
fs.writeFileSync(path.join(outDir, "loader.js"), loaderJs, "utf8");

// 5. Copy styles.css and app.js
fs.copyFileSync(path.join(root, "styles.css"), path.join(outDir, "styles.css"));
fs.copyFileSync(path.join(root, "app.js"), path.join(outDir, "app.js"));

console.log("Encrypted site built in", outDir);
