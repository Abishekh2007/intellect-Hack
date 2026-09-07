import jsPDF from "jspdf";

/*
 * Exports deliberately avoid html2canvas.
 *
 * html2canvas rasterises the DOM by re-parsing computed CSS, and it cannot
 * parse `oklch()` colours — which this design system uses throughout — so it
 * threw on every chart and both downloads silently produced nothing.
 *
 * ECharts already renders to a canvas, so it can hand us a PNG directly at
 * any pixel ratio. That is both more reliable and sharper than rasterising
 * the surrounding DOM.
 */

/** A cell as it arrives from the query API. */
type Cell = string | number | boolean | null | undefined;

export function exportCsv(
  columns: string[],
  rows: readonly Cell[][],
  filename: string = "export.csv",
) {
  const escapeCell = (cell: Cell) => {
    if (cell === null || cell === undefined) return "";
    const str = String(cell);
    if (str.includes(",") || str.includes('"') || str.includes("\n")) {
      return `"${str.replace(/"/g, '""')}"`;
    }
    return str;
  };

  const csvContent = [
    columns.map(escapeCell).join(","),
    ...rows.map((row) => row.map(escapeCell).join(",")),
  ].join("\r\n");

  // A UTF-8 BOM, and CRLF line endings above. Without them Excel opens the
  // file in the local ANSI codepage and mangles every non-ASCII character.
  download(
    URL.createObjectURL(new Blob(["﻿", csvContent], { type: "text/csv;charset=utf-8;" })),
    filename,
    true,
  );
}

function download(href: string, filename: string, revoke = false) {
  const link = document.createElement("a");
  link.href = href;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  if (revoke) {
    // Revoking in the same tick can invalidate the URL before the browser has
    // started reading it, which produced a silently empty or failed CSV
    // download. One frame plus a beat is enough for every engine.
    setTimeout(() => URL.revokeObjectURL(href), 10_000);
  }
}

export function savePng(dataUrl: string, filename = "chart.png") {
  download(dataUrl, filename);
}

/** Fit a PNG onto a single PDF page at its own aspect ratio. */
export function savePdf(dataUrl: string, filename = "chart.pdf"): Promise<void> {
  // Returns a promise so a failure is reportable. The bare `image.onload`
  // callback had no `onerror`, so a bad data URL simply did nothing at all.
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      try {
        const landscape = image.width >= image.height;
        const pdf = new jsPDF({
          orientation: landscape ? "landscape" : "portrait",
          unit: "pt",
          format: "a4",
        });
        const margin = 32;
        const pageW = pdf.internal.pageSize.getWidth() - margin * 2;
        const pageH = pdf.internal.pageSize.getHeight() - margin * 2;
        const scale = Math.min(pageW / image.width, pageH / image.height);
        const w = image.width * scale;
        const h = image.height * scale;
        pdf.addImage(dataUrl, "PNG", (pageW - w) / 2 + margin, (pageH - h) / 2 + margin, w, h);
        pdf.save(filename);
        resolve();
      } catch (err) {
        reject(err);
      }
    };
    image.onerror = () => reject(new Error("Could not read the exported image."));
    image.src = dataUrl;
  });
}

/** Render a KPI card to a PNG, since it has no ECharts canvas behind it. */
export function kpiDataUrl(
  label: string,
  value: string,
  colors: { background: string; text: string; muted: string },
): string {
  const width = 800;
  const height = 400;
  const canvas = document.createElement("canvas");
  canvas.width = width * 2;
  canvas.height = height * 2;
  const ctx = canvas.getContext("2d");
  if (!ctx) return "";
  ctx.scale(2, 2);

  ctx.fillStyle = colors.background;
  ctx.fillRect(0, 0, width, height);

  ctx.textAlign = "center";
  ctx.fillStyle = colors.muted;
  ctx.font = "500 20px Inter, system-ui, sans-serif";
  ctx.fillText(label.toUpperCase(), width / 2, height / 2 - 48);

  ctx.fillStyle = colors.text;
  ctx.font = "600 84px Inter, system-ui, sans-serif";
  ctx.fillText(value, width / 2, height / 2 + 48);

  return canvas.toDataURL("image/png");
}

/** Rasterise an inline SVG (Mermaid diagrams) to a PNG data URL. */
export function svgToPng(svg: SVGElement, background: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const box = svg.getBoundingClientRect();
    const width = Math.max(1, Math.round(box.width || 800));
    const height = Math.max(1, Math.round(box.height || 600));

    // Clone so the inlined size doesn't affect the element on screen.
    const clone = svg.cloneNode(true) as SVGElement;
    clone.setAttribute("width", String(width));
    clone.setAttribute("height", String(height));
    clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");

    const blob = new Blob([new XMLSerializer().serializeToString(clone)], {
      type: "image/svg+xml;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const image = new Image();
    image.onload = () => {
      // The whole body is guarded. `toDataURL` throws SecurityError on a
      // tainted canvas, and a throw inside an onload handler does not reject
      // the surrounding promise — it escapes as an uncaught error and leaves
      // the promise pending forever. That is exactly how diagram export came
      // to hang with no download and no error message.
      try {
        const canvas = document.createElement("canvas");
        canvas.width = width * 2;
        canvas.height = height * 2;
        const ctx = canvas.getContext("2d");
        if (!ctx) {
          reject(new Error("Canvas is unavailable"));
          return;
        }
        ctx.scale(2, 2);
        ctx.fillStyle = background;
        ctx.fillRect(0, 0, width, height);
        ctx.drawImage(image, 0, 0, width, height);
        resolve(canvas.toDataURL("image/png"));
      } catch (err) {
        reject(err instanceof Error ? err : new Error("Could not rasterise the diagram"));
      } finally {
        URL.revokeObjectURL(url);
      }
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("Could not rasterise the diagram"));
    };
    image.src = url;
  });
}
