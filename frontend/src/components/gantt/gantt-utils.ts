export function addDays(date: Date, days: number): Date {
  const result = new Date(date);
  result.setDate(result.getDate() + days);
  return result;
}

export function diffDays(a: Date, b: Date): number {
  const msPerDay = 86400000;
  return Math.round((b.getTime() - a.getTime()) / msPerDay);
}

export function startOfWeek(date: Date): Date {
  const d = new Date(date);
  d.setDate(d.getDate() - d.getDay());
  d.setHours(0, 0, 0, 0);
  return d;
}

export function formatDate(date: Date): string {
  return date.toISOString().split("T")[0];
}

export function parseDate(str: string): Date {
  const [y, m, d] = str.split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function formatShortDate(date: Date): string {
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export type ZoomLevel = "week" | "2week" | "month" | "quarter";

export function getZoomDays(zoom: ZoomLevel): number {
  switch (zoom) {
    case "week": return 7;
    case "2week": return 14;
    case "month": return 30;
    case "quarter": return 90;
  }
}

export function getColumnWidth(zoom: ZoomLevel): number {
  switch (zoom) {
    case "week": return 120;
    case "2week": return 60;
    case "month": return 28;
    case "quarter": return 10;
  }
}
