export function formatCount(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString() : '未知';
}

export function formatPercent(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value)
    ? `${(value * 100).toFixed(1)}%`
    : '未知';
}

export function formatBytes(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value)
    ? `${value.toLocaleString()}B`
    : '未知';
}

export function formatByteSizeHuman(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '未知';
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`;
  return `${(value / (1024 * 1024)).toFixed(2)} MiB`;
}

export function formatDuration(ms: number | null | undefined): string {
  if (typeof ms !== 'number' || !Number.isFinite(ms)) return '未知';
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(ms >= 10000 ? 1 : 2)} s`;
}

export function formatSeconds(seconds: number | null | undefined): string {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds)) return '未知';
  if (seconds % 86400 === 0 && seconds >= 86400) return `${seconds / 86400} 天`;
  if (seconds % 3600 === 0 && seconds >= 3600) return `${seconds / 3600} 小时`;
  return `${seconds} 秒`;
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '未报告';
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? date.toLocaleString() : '未报告';
}

export function formatShortTime(value: string | null | undefined): string {
  if (!value) return '未报告';
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return '未报告';
  try {
    return date.toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    });
  } catch {
    return date.toLocaleTimeString();
  }
}

export function formatRelativeAgo(value: string | null | undefined, nowMs = Date.now()): string {
  const timestamp = value ? Date.parse(value) : NaN;
  if (!Number.isFinite(timestamp)) return '时间未报告';
  const seconds = Math.max(0, Math.floor((nowMs - timestamp) / 1000));
  if (seconds < 60) return '刚刚';
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`;
  return `${Math.floor(seconds / 86400)} 天前`;
}

export function formatBoolState(value: boolean | null | undefined, yes = '是', no = '否'): string {
  if (value === true) return yes;
  if (value === false) return no;
  return '未知';
}
