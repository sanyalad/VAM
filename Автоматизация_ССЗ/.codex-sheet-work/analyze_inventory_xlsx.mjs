import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const inputPath = process.argv[2];
const outputDir = process.argv[3];
if (!inputPath || !outputDir) {
  throw new Error("Usage: analyze_inventory_xlsx.mjs <input.xlsx> <output-dir>");
}

await fs.mkdir(outputDir, { recursive: true });
const input = await FileBlob.load(inputPath);
const workbook = await SpreadsheetFile.importXlsx(input);

const summary = await workbook.inspect({
  kind: "workbook,sheet,table,region,computedStyle",
  maxChars: 14000,
  tableMaxRows: 40,
  tableMaxCols: 20,
  tableMaxCellChars: 160,
});
console.log(summary.ndjson);

const sheets = workbook.worksheets.items;
for (let index = 0; index < sheets.length; index += 1) {
  const sheet = sheets[index];
  const preview = await workbook.render({
    sheetName: sheet.name,
    autoCrop: "all",
    scale: 1.5,
    format: "png",
  });
  const safeName = sheet.name.replace(/[\\/:*?"<>|]/g, "_");
  await fs.writeFile(
    `${outputDir}/${String(index + 1).padStart(2, "0")}_${safeName}.png`,
    new Uint8Array(await preview.arrayBuffer()),
  );
}
