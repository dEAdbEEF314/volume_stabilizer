// DOM-independent track list view logic (To Do / Processed split, paging, selection).
var TrackView = (function () {
  var PAGE_SIZES = [10, 20, 50, 100, "all"];
  var DEFAULT_PAGE_SIZE = 10;
  var PAGE_LINK_COUNT = 5;

  function isProcessed(t) {
    return t.status === "converted" || t.status === "bypassed";
  }

  function partition(tracks) {
    var todo = [];
    var processed = [];
    tracks.forEach(function (t) {
      (isProcessed(t) ? processed : todo).push(t);
    });
    return { todo: todo, processed: processed };
  }

  function normalizePageSize(value) {
    if (value === "all") return "all";
    var n = Number(value);
    return PAGE_SIZES.indexOf(n) !== -1 ? n : DEFAULT_PAGE_SIZE;
  }

  // Up to PAGE_LINK_COUNT page numbers, centered on the current page where possible.
  function pageLinks(current, totalPages) {
    var count = Math.min(PAGE_LINK_COUNT, totalPages);
    var start = Math.min(Math.max(current - 2, 1), totalPages - count + 1);
    var links = [];
    for (var i = 0; i < count; i++) links.push(start + i);
    return links;
  }

  // pageSize undefined is treated as "all" (no paging).
  function paginate(items, pageSize, page) {
    var total = items.length;
    var size = pageSize === undefined || pageSize === "all" ? Math.max(total, 1) : pageSize;
    var totalPages = Math.max(1, Math.ceil(total / size));
    var current = Math.min(Math.max(parseInt(page, 10) || 1, 1), totalPages);
    var offset = (current - 1) * size;
    return {
      items: items.slice(offset, offset + size),
      page: current,
      totalPages: totalPages,
      total: total,
      start: total ? offset + 1 : 0,
      end: Math.min(offset + size, total),
      links: pageLinks(current, totalPages),
      showPager: totalPages > 1,
      hasPrev: current > 1,
      hasNext: current < totalPages
    };
  }

  function resolveTab(parts, activeTab) {
    return activeTab === "processed" && parts.processed.length > 0 ? "processed" : "todo";
  }

  function buildView(tracks, activeTab, processedExpanded, pageSize, page) {
    var parts = partition(tracks);
    var stabilizedCount = parts.processed.filter(function (t) { return t.status === "converted"; }).length;
    var bypassedCount = parts.processed.length - stabilizedCount;

    var tab = resolveTab(parts, activeTab);
    var all = tab === "todo" ? parts.todo : parts.processed;
    var paging = paginate(all, pageSize, page);
    var showToggle = tab === "todo" && parts.processed.length > 0;
    var expanded = showToggle && !!processedExpanded;
    var trailing = [];
    if (expanded) {
      trailing = pageSize === undefined || pageSize === "all"
        ? parts.processed
        : parts.processed.slice(0, pageSize);
    }

    var empty = null;
    if (all.length === 0) {
      empty = parts.processed.length > 0 ? "all-processed" : "no-tracks";
    }

    return {
      tab: tab,
      todoCount: parts.todo.length,
      processedCount: parts.processed.length,
      stabilizedCount: stabilizedCount,
      bypassedCount: bypassedCount,
      main: paging.items,
      paging: paging,
      trailing: trailing,
      trailingHidden: expanded ? parts.processed.length - trailing.length : 0,
      showToggle: showToggle,
      expanded: expanded,
      empty: empty
    };
  }

  // Unprocessed tracks default to selected, processed ones to unselected; overrides is {id: bool}.
  function isSelected(t, overrides) {
    if (Object.prototype.hasOwnProperty.call(overrides, t.id)) return !!overrides[t.id];
    return !isProcessed(t);
  }

  // Selection spans every page of the active tab; the Processed tab only considers processed tracks.
  function collectSelectedIds(tracks, activeTab, overrides) {
    var parts = partition(tracks);
    var pool = resolveTab(parts, activeTab) === "processed" ? parts.processed : tracks;
    return pool.filter(function (t) { return isSelected(t, overrides); })
      .map(function (t) { return t.id; });
  }

  return {
    PAGE_SIZES: PAGE_SIZES,
    DEFAULT_PAGE_SIZE: DEFAULT_PAGE_SIZE,
    isProcessed: isProcessed,
    partition: partition,
    normalizePageSize: normalizePageSize,
    pageLinks: pageLinks,
    paginate: paginate,
    buildView: buildView,
    isSelected: isSelected,
    collectSelectedIds: collectSelectedIds
  };
})();
