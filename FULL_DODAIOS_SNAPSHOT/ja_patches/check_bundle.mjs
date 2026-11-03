// Compila cada bundle sem executar. Diferente de `node --check`, detecta regex
// invalido dentro de funcoes. Uso: node --experimental-vm-modules check_bundle.mjs <pasta>
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

function* walk(target) {
  if (fs.statSync(target).isFile()) { yield target; return; }
  for (const entry of fs.readdirSync(target, { withFileTypes: true })) {
    const full = path.join(target, entry.name);
    if (entry.isDirectory()) yield* walk(full);
    else if (/\.m?js$/.test(entry.name)) yield full;
  }
}

let checked = 0;
let bad = 0;
for (const file of process.argv.slice(2).flatMap((t) => [...walk(t)])) {
  checked += 1;
  const code = fs.readFileSync(file, "utf8");
  try {
    new vm.SourceTextModule(code);
  } catch (error) {
    let failed = /regular expression/i.test(error.message);
    if (!failed) {
      try { new vm.Script(code); } catch { failed = true; }
    }
    if (failed) {
      bad += 1;
      console.log(`BUNDLE_INVALIDO ${file}: ${error.message}`);
    }
  }
}
console.log(`BUNDLES_VERIFICADOS=${checked} INVALIDOS=${bad}`);
process.exit(bad === 0 && checked > 0 ? 0 : 1);
