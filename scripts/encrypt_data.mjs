import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.dirname(__dirname);
const srcPath = path.join(root, "data", "booster_data.json");
const outPath = path.join(root, "data", "booster_data.enc");

const KEY_HEX = "9f3c8a1e7b24d065a8e1c43f5d902b7e61a4c8d20e3f7b95a1c6d4e802b3f791";
const key = Buffer.from(KEY_HEX, "hex");
const iv = crypto.randomBytes(12);
const plain = fs.readFileSync(srcPath);

const cipher = crypto.createCipheriv("aes-256-gcm", key, iv);
const ct = Buffer.concat([cipher.update(plain), cipher.final(), cipher.getAuthTag()]);

fs.writeFileSync(
  outPath,
  JSON.stringify({ v: 1, iv: iv.toString("base64"), d: ct.toString("base64") })
);
console.log(`Encrypted ${srcPath} -> ${outPath} (${ct.length} bytes)`);
