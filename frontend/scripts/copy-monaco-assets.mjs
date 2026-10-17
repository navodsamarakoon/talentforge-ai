import { cpSync, existsSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";

const source = resolve("node_modules/monaco-editor/min/vs");
const destination = resolve("public/vs");

if (!existsSync(source)) {
  throw new Error("Monaco Editor assets are missing. Run npm ci before starting the frontend.");
}

mkdirSync(resolve("public"), { recursive: true });
cpSync(source, destination, { recursive: true });
