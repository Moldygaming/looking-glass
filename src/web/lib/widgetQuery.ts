import { qs } from "@/lib/api";
import type { Widget } from "@/lib/types";

export function widgetQuery(widget: Widget, extra: Record<string, string | number | undefined | null> = {}) {
  const tags = [
    ...(widget.tag_key && widget.tag_value ? [`${widget.tag_key}=${widget.tag_value}`] : []),
    ...(widget.tag_filters || [])
      .filter((item) => item.key && item.value)
      .map((item) => `${item.key}=${item.value}`),
  ].join(",");
  return qs({
    group_by: widget.group_by,
    provider: widget.provider,
    service: widget.service,
    resource_type: widget.resource_type,
    category: widget.category,
    q: widget.q,
    tag_key: widget.tag_key,
    tag_value: widget.tag_value,
    tags,
    granularity: widget.granularity || "day",
    keys: (widget.item_keys || []).join(","),
    limit: widget.limit || 20,
    ...extra,
  });
}

export function widgetHint(widget: Widget) {
  const parts: string[] = [];
  if (widget.provider) parts.push(widget.provider);
  if (widget.category) parts.push(widget.category);
  if (widget.resource_type) parts.push(widget.resource_type);
  if (widget.service) parts.push(widget.service);
  const tags = [
    ...(widget.tag_key && widget.tag_value ? [`${widget.tag_key}=${widget.tag_value}`] : []),
    ...(widget.tag_filters || []).filter((item) => item.key && item.value).map((item) => `${item.key}=${item.value}`),
  ];
  if (tags.length) parts.push(tags.join(", "));
  parts.push(`by ${widget.group_by}`);
  return parts.join(" · ");
}
