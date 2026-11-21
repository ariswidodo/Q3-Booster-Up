(() => {
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
