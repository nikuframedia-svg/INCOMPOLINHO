// Read-only three-way inventory; this script never copies code into production.
import { createHash } from "node:crypto";
import { readdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";

const [baseline, isolated, published, output] = process.argv.slice(2);
if (!baseline || !isolated || !published || !output) {
  throw new Error("Expected baseline, isolated, published and output paths");
}
const scopes = ["backend", "frontend/src", "frontend/tests", "tests", "scripts", "docs"];
const excluded = new Set(["__pycache__", "node_modules", ".pytest_cache", ".ruff_cache"]);

async function inventory(root) {
  const files = new Map();
  async function visit(relative) {
    let entries;
    try { entries = await readdir(join(root, relative), { withFileTypes: true }); }
    catch (error) { if (error.code === "ENOENT") return; throw error; }
    for (const entry of entries) {
      if (excluded.has(entry.name)) continue;
      const path = join(relative, entry.name);
      if (entry.isDirectory()) await visit(path);
      else if (entry.isFile()) files.set(path, createHash("sha256").update(await readFile(join(root, path))).digest("hex"));
    }
  }
  for (const scope of scopes) await visit(scope);
  return files;
}

const initial = await inventory(baseline);
const edited = await inventory(isolated);
const live = await inventory(published);
const changes = [];
for (const path of [...new Set([...initial.keys(), ...edited.keys()])].sort()) {
  if (initial.get(path) === edited.get(path)) continue;
  changes.push({ path, initial: initial.get(path) ?? null, edited: edited.get(path) ?? null,
    live: live.get(path) ?? null, conflict: live.get(path) !== initial.get(path) && live.get(path) !== edited.get(path) });
}
const result = { baseline, isolated, published, excluded: ["config", "data", "dependencies", "build outputs"], changes };
await writeFile(output, JSON.stringify(result, null, 2));
console.log(JSON.stringify({ files: changes.length, conflicts: changes.filter((item) => item.conflict).map((item) => item.path) }));
