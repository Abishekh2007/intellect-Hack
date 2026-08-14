import html2canvas from "html2canvas";
import jsPDF from "jspdf";

export function exportCsv(columns: string[], rows: any[][], filename: string = "export.csv") {
  const escapeCell = (cell: any) => {
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
  ].join("\n");

  const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.setAttribute("href", url);
  link.setAttribute("download", filename);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

export async function exportImage(element: HTMLElement, filename: string = "chart.png") {
  try {
    const canvas = await html2canvas(element, { backgroundColor: null, scale: 2 });
    const url = canvas.toDataURL("image/png");
    const link = document.createElement("a");
    link.setAttribute("href", url);
    link.setAttribute("download", filename);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  } catch (error) {
    console.error("Failed to export image", error);
  }
}

export async function exportPdf(element: HTMLElement, filename: string = "chart.pdf") {
  try {
    const canvas = await html2canvas(element, { backgroundColor: "#ffffff", scale: 2 });
    const imgData = canvas.toDataURL("image/png");
    
    // Create a landscape PDF if the element is wider than tall, else portrait
    const isLandscape = canvas.width > canvas.height;
    const pdf = new jsPDF({
      orientation: isLandscape ? "landscape" : "portrait",
      unit: "px",
      format: [canvas.width, canvas.height]
    });
    
    pdf.addImage(imgData, "PNG", 0, 0, canvas.width, canvas.height);
    pdf.save(filename);
  } catch (error) {
    console.error("Failed to export PDF", error);
  }
}
