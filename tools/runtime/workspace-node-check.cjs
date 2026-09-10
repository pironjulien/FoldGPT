'use strict';
// Real native rendering and OOXML export, used by installation and Diagnose.
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const { createRequire } = require('node:module');
const { pathToFileURL } = require('node:url');

async function main() {
  assert.equal(process.arch, 'arm64');
  const root = process.argv[2] ? path.resolve(process.argv[2]) : path.resolve(__dirname, '..');
  const load = createRequire(path.join(root, 'dependencies/node/package.json'));
  const directory = await fs.mkdtemp('/tmp/foldgpt-workspace-node-');
  try {
    const canvas = load('@napi-rs/canvas').createCanvas(16, 16);
    canvas.getContext('2d').fillRect(0, 0, 16, 16);
    const png = canvas.toBuffer('image/png');
    assert.deepEqual([...png.subarray(0, 4)], [137, 80, 78, 71]);
    const sharp = load('sharp');
    assert.equal((await sharp(png).resize(8, 8).toBuffer({ resolveWithObject: true })).info.width, 8);
    const skia = load(path.join(root, 'dependencies/node/node_modules/@oai/artifact-tool/node_modules/skia-canvas/lib/index.js'));
    const skiaCanvas = new skia.Canvas(16, 16);
    skiaCanvas.getContext('2d').fillText('12', 0, 12);
    assert.ok((await skiaCanvas.toBuffer('png')).length > 0);
    const { Workbook, SpreadsheetFile } = await import(pathToFileURL(load.resolve('@oai/artifact-tool')));
    const workbook = Workbook.create();
    const sheet = workbook.worksheets.add('Check');
    sheet.getRange('A1:A3').values = [[2], [4], [6]];
    sheet.getRange('B1').formulas = [['=SUM(A1:A3)']];
    assert.equal(sheet.getRange('B1').values[0][0], 12);
    await (await SpreadsheetFile.exportXlsx(workbook)).save(path.join(directory, 'artifact.xlsx'));
    const archive = await load('jszip').loadAsync(await fs.readFile(path.join(directory, 'artifact.xlsx')));
    assert.match(await archive.file('xl/worksheets/sheet1.xml').async('string'), /12/);
    const { PDFDocument } = load('pdf-lib');
    const pdf = await PDFDocument.create();
    pdf.addPage();
    assert.equal((await PDFDocument.load(await pdf.save())).getPageCount(), 1);
    const { Document, Packer, Paragraph } = load('docx');
    assert.ok((await Packer.toBuffer(new Document({ sections: [{ children: [new Paragraph('FoldGPT')] }] }))).length);
    const PptxGenJS = load('pptxgenjs');
    const ppt = new PptxGenJS();
    ppt.addSlide().addText('FoldGPT', { x: 1, y: 1, w: 4, h: 1 });
    assert.ok((await ppt.write({ outputType: 'nodebuffer' })).length);
    assert.ok(load('playwright').chromium);
    console.log(JSON.stringify({ passed: true, node: process.version, arch: process.arch,
      checks: ['canvas', 'sharp', 'skia', 'artifact-xlsx-formula', 'pdf', 'docx', 'pptx', 'playwright-module'] }));
  } finally {
    await fs.rm(directory, { recursive: true, force: true });
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
