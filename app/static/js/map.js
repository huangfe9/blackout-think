"use strict";
window.BlackoutMap = (function () {
  const SVG_NAMESPACE = "http://www.w3.org/2000/svg";
  const HORIZONTAL_STRETCH = 1.45;
  const MAX_LABEL_UNITS = 24;
  const LABEL_OFFSET = 16;
  const LABEL_BOX_OFFSET = 15;
  const COLLISION_PASSES = 40;
  const COLLISION_PADDING = 6;
  const COLLISION_STEP = 14;
  const NIGHT_LABEL_CSS = 18;
  const NIGHT_BRANCH_CSS = 20;
  const NIGHT_GOAL_CSS = 24;
  const PAPER_LABEL_CSS = 15;
  const PAPER_BRANCH_CSS = 17;
  const PAPER_GOAL_CSS = 20;
  let activeTheme = "night";
  let activeUnitPerCss = 1;
  let activeMarkScale = 1;
  let activeDimIds = {};
  let activeNewestId = "";
  const renderRegistry = [];
  let resizeTimer = 0;
  function prefersReducedMotion() {
    try {
      const query = window.matchMedia("(prefers-reduced-motion: reduce)");
      return Boolean(query && query.matches);
    } catch (error) {
      return false;
    }
  }
  function isDocumentHidden() {
    try {
      return Boolean(document.hidden);
    } catch (error) {
      return false;
    }
  }
  function radiusForDepth(depth) {
    if (depth <= 0) {
      return 0;
    }
    if (depth === 1) {
      return 190;
    }
    if (depth === 2) {
      return 330;
    }
    if (depth === 3) {
      return 460;
    }
    return 460 + (depth - 3) * 120;
  }
  function leafCount(node) {
    const children = node.children || [];
    if (!children.length) {
      return 1;
    }
    let total = 0;
    children.forEach(function (child) {
      total += leafCount(child);
    });
    return Math.max(1, total);
  }
  function characterUnits(text) {
    let units = 0;
    String(text).split("").forEach(function (character) {
      units += character.charCodeAt(0) > 255 ? 2 : 1;
    });
    return units;
  }
  function tokenizeLabel(text) {
    const source = String(text || "");
    const tokens = [];
    let index = 0;
    while (index < source.length) {
      const character = source[index];
      if (/[A-Za-z0-9-]/.test(character)) {
        let end = index + 1;
        while (end < source.length && /[A-Za-z0-9-]/.test(source[end])) {
          end += 1;
        }
        tokens.push(source.slice(index, end));
        index = end;
      } else {
        tokens.push(character);
        index += 1;
      }
    }
    return tokens;
  }
  function splitLongToken(token, maxUnits) {
    if (characterUnits(token) <= maxUnits) {
      return [token];
    }
    const pieces = [];
    let piece = "";
    String(token).split("").forEach(function (character) {
      const units = character.charCodeAt(0) > 255 ? 2 : 1;
      if (piece && characterUnits(piece) + units > maxUnits) {
        pieces.push(piece);
        piece = character;
      } else {
        piece += character;
      }
    });
    if (piece) {
      pieces.push(piece);
    }
    return pieces.length ? pieces : [token];
  }
  function tokensWithLimit(text, maxUnits) {
    const tokens = [];
    tokenizeLabel(text).forEach(function (token) {
      splitLongToken(token, maxUnits).forEach(function (piece) {
        tokens.push(piece);
      });
    });
    return tokens;
  }
  function trimLineEnd(line) {
    return String(line).replace(/\s+$/, "");
  }
  function splitBalanced(text, lineCount) {
    const tokens = tokensWithLimit(text, MAX_LABEL_UNITS);
    const targetUnits = characterUnits(text) / lineCount;
    const lines = [];
    let line = "";
    let units = 0;
    tokens.forEach(function (token) {
      const tokenUnits = characterUnits(token);
      const canBreak = lines.length < lineCount - 1;
      if (canBreak && line && units + tokenUnits > targetUnits) {
        lines.push(trimLineEnd(line));
        line = token === " " ? "" : token;
        units = line ? tokenUnits : 0;
      } else {
        line += token;
        units += tokenUnits;
      }
      if (!line && token === " ") {
        units = 0;
      }
    });
    if (line || !lines.length) {
      lines.push(trimLineEnd(line));
    }
    while (lines.length < lineCount) {
      lines.push("");
    }
    return lines;
  }
  function wrapGoalLabel(text) {
    const units = characterUnits(text);
    let lineCount = 1;
    if (units > 28) {
      lineCount = 3;
    } else if (units > 14) {
      lineCount = 2;
    }
    return { lines: splitBalanced(text, lineCount), full: String(text || "") };
  }
  function truncateToUnits(text, maxUnits) {
    const tokens = tokenizeLabel(text);
    let result = "";
    for (let index = 0; index < tokens.length; index += 1) {
      const token = tokens[index];
      if (result && characterUnits(result + token) > maxUnits) {
        break;
      }
      if (!result && characterUnits(token) > maxUnits) {
        const pieces = splitLongToken(token, maxUnits);
        pieces.forEach(function (piece) {
          if (characterUnits(result + piece) <= maxUnits) {
            result += piece;
          }
        });
        break;
      }
      result += token;
    }
    return trimLineEnd(result);
  }
  function wrapLabel(text, nodeKind, taskStatus, isGoal) {
    let fullText = String(text || "");
    if (isGoal) {
      return wrapGoalLabel(fullText);
    }
    if (nodeKind === "task" && taskStatus === "running") {
      const prefix = fullText.indexOf("写") >= 0 ? "在写：" : "在查：";
      fullText = prefix + fullText;
    }
    const tokens = tokensWithLimit(fullText, MAX_LABEL_UNITS);
    const lines = [];
    let line = "";
    tokens.forEach(function (token) {
      if (!line && token === " ") {
        return;
      }
      if (line && characterUnits(line + token) > MAX_LABEL_UNITS) {
        lines.push(trimLineEnd(line));
        line = token === " " ? "" : token;
      } else {
        line += token;
      }
    });
    if (line) {
      lines.push(trimLineEnd(line));
    }
    if (!lines.length) {
      lines.push("");
    }
    if (lines.length > 2) {
      const second = truncateToUnits(lines[1], MAX_LABEL_UNITS - 2);
      return { lines: [lines[0], second + "…"], full: fullText };
    }
    return { lines: lines, full: fullText };
  }
  function flattenTree(node, depth, out) {
    out.push({ node: node, depth: depth });
    (node.children || []).forEach(function (child) {
      flattenTree(child, depth + 1, out);
    });
    return out;
  }
  function prepareActiveDisplay(svgElement, tree, theme) {
    activeTheme = theme;
    activeDimIds = {};
    activeNewestId = "";
    const flat = flattenTree(tree, 0, []);
    const previousOrder = svgElement._blackoutSeenOrder || [];
    const hadPrevious = previousOrder.length > 0;
    const order = previousOrder.slice();
    const newIds = [];
    flat.forEach(function (entry) {
      const id = String(entry.node.id);
      if (order.indexOf(id) < 0) {
        order.push(id);
        newIds.push(id);
      }
    });
    svgElement._blackoutSeenOrder = order;
    if (hadPrevious && newIds.length) {
      activeNewestId = newIds[newIds.length - 1];
      svgElement._blackoutNewestId = activeNewestId;
      svgElement._blackoutNewestUntil = Date.now() + 3000;
    }
    if (theme === "paper") {
      return;
    }
    const recent = {};
    order.slice(-8).forEach(function (id) { recent[id] = true; });
    flat.forEach(function (entry) {
      const id = String(entry.node.id);
      const isLeaf = !(entry.node.children || []).length;
      if (isLeaf && entry.depth > 1 && !recent[id]) {
        activeDimIds[id] = true;
      }
    });
  }
  function layoutTree(tree) {
    let maxDepth = 0;
    (function measureDepth(node, depth) {
      maxDepth = Math.max(maxDepth, depth);
      (node.children || []).forEach(function (child) {
        measureDepth(child, depth + 1);
      });
    })(tree, 0);
    const totalLeaves = leafCount(tree);
    let radii = [];
    for (let depth = 0; depth <= maxDepth; depth += 1) {
      radii.push(radiusForDepth(depth));
    }
    radii = widenRadiiIfCrowded(radii, maxDepth, totalLeaves);
    const nodes = [];
    const nodesById = {};
    placeNode(tree, 0, -Math.PI / 2, Math.PI * 1.5, null, radii, nodes, nodesById);
    resolveLabelCollisions(nodes);
    return { nodes: nodes, byId: nodesById, radii: radii };
  }
  function widenRadiiIfCrowded(radii, maxDepth, totalLeaves) {
    if (maxDepth <= 0 || totalLeaves <= 1) {
      return radii;
    }
    const needed = activeTheme === "paper" ? 56 : 110;
    const outerRadius = radii[maxDepth] * HORIZONTAL_STRETCH;
    const arcPerLeaf = (2 * Math.PI * outerRadius) / Math.max(1, totalLeaves);
    if (arcPerLeaf >= needed) {
      return radii;
    }
    const scale = needed / Math.max(1, arcPerLeaf);
    return radii.map(function (radius) {
      return radius * scale;
    });
  }
  function placeNode(node, depth, start, end, parent, radii, nodes, nodesById) {
    const angle = depth === 0 ? -Math.PI / 2 : (start + end) / 2;
    const radius = radii[depth] || radiusForDepth(depth);
    const item = {
      node: node,
      depth: depth,
      angle: angle,
      x: depth === 0 ? 0 : Math.cos(angle) * radius * HORIZONTAL_STRETCH,
      y: depth === 0 ? 0 : Math.sin(angle) * radius,
      parent: parent
    };
    nodes.push(item);
    nodesById[String(node.id)] = item;
    const children = node.children || [];
    const subtreeLeaves = leafCount(node);
    let cursor = start;
    children.forEach(function (child) {
      const span = (end - start) * (leafCount(child) / subtreeLeaves);
      placeNode(child, depth + 1, cursor, cursor + span, item, radii, nodes, nodesById);
      cursor += span;
    });
    return item;
  }
  function labelBoxForItem(item) {
    const wrapped = wrappedForItem(item);
    const width = labelWidth(wrapped.lines, item.node.kind, item.depth);
    const lineHeight = item.node.kind === "goal" ? fontSizeForKind("goal", 0) * 1.08 : fontSizeForKind(item.node.kind, item.depth) * 1.1;
    const height = Math.max(lineHeight, wrapped.lines.length * lineHeight);
    let left = item.x - width / 2;
    if (item.depth !== 0) {
      const pointsRight = Math.cos(item.angle) >= 0;
      left = pointsRight ? item.x + LABEL_BOX_OFFSET : item.x - LABEL_BOX_OFFSET - width;
    }
    const top = item.depth === 0 ? item.y - height / 2 : item.y - 12;
    return {
      left: left - COLLISION_PADDING,
      right: left + width + COLLISION_PADDING,
      top: top - COLLISION_PADDING,
      bottom: top + height + COLLISION_PADDING,
      width: width,
      height: height
    };
  }
  function boxesOverlap(firstBox, secondBox) {
    const overlapsX = firstBox.left < secondBox.right && firstBox.right > secondBox.left;
    const overlapsY = firstBox.top < secondBox.bottom && firstBox.bottom > secondBox.top;
    return overlapsX && overlapsY;
  }
  function distanceFromCenter(item) {
    return Math.hypot(item.x, item.y);
  }
  function fartherItem(firstItem, secondItem) {
    if (firstItem.depth === 0) {
      return secondItem;
    }
    if (secondItem.depth === 0) {
      return firstItem;
    }
    const firstDistance = distanceFromCenter(firstItem);
    const secondDistance = distanceFromCenter(secondItem);
    if (firstDistance !== secondDistance) {
      return firstDistance > secondDistance ? firstItem : secondItem;
    }
    return firstItem.depth >= secondItem.depth ? firstItem : secondItem;
  }
  function pushItemOutward(item, amount) {
    const distance = distanceFromCenter(item);
    let directionX = Math.cos(item.angle);
    let directionY = Math.sin(item.angle);
    if (distance > 0.001) {
      directionX = item.x / distance;
      directionY = item.y / distance;
    }
    item.x += directionX * amount;
    item.y += directionY * amount;
  }
  function overlapAmount(firstBox, secondBox) {
    const overlapX = Math.min(firstBox.right, secondBox.right) - Math.max(firstBox.left, secondBox.left);
    const overlapY = Math.min(firstBox.bottom, secondBox.bottom) - Math.max(firstBox.top, secondBox.top);
    const smallerOverlap = Math.min(Math.max(overlapX, 0), Math.max(overlapY, 0));
    return Math.max(COLLISION_STEP, smallerOverlap + COLLISION_PADDING);
  }
  function resolveLabelCollisions(items) {
    for (let pass = 0; pass < COLLISION_PASSES; pass += 1) {
      let movedAny = false;
      for (let firstIndex = 0; firstIndex < items.length; firstIndex += 1) {
        for (let secondIndex = firstIndex + 1; secondIndex < items.length; secondIndex += 1) {
          const firstItem = items[firstIndex];
          const secondItem = items[secondIndex];
          const firstBox = labelBoxForItem(firstItem);
          const secondBox = labelBoxForItem(secondItem);
          if (!boxesOverlap(firstBox, secondBox)) {
            continue;
          }
          if (firstItem.depth === 0 && secondItem.depth === 0) {
            continue;
          }
          const itemToMove = fartherItem(firstItem, secondItem);
          pushItemOutward(itemToMove, overlapAmount(firstBox, secondBox));
          movedAny = true;
        }
      }
      if (!movedAny) {
        break;
      }
    }
  }
  function paletteForTheme(theme) {
    if (theme === "paper") {
      return {
        line: "#8f8672", text: "#1c1a17", dim: "#6b655a", star: "#1c1a17",
        amber: "#b07d1e", signal: "#e5604d", parked: "#7d93b2"
      };
    }
    return {
      line: "#6f6a5e", text: "#f4efe6", dim: "#8a8478", star: "#f4efe6",
      amber: "#e8b44c", signal: "#e5604d", parked: "#7d93b2"
    };
  }
  function createSvgElement(tag, attributes) {
    const element = document.createElementNS(SVG_NAMESPACE, tag);
    Object.keys(attributes || {}).forEach(function (key) {
      element.setAttribute(key, String(attributes[key]));
    });
    return element;
  }
  function cssFontForKind(kind, depth) {
    if (activeTheme === "paper") {
      if (kind === "goal") { return PAPER_GOAL_CSS; }
      return depth <= 1 ? PAPER_BRANCH_CSS : PAPER_LABEL_CSS;
    }
    if (kind === "goal") { return NIGHT_GOAL_CSS; }
    return depth <= 1 ? NIGHT_BRANCH_CSS : NIGHT_LABEL_CSS;
  }
  function fontSizeForKind(kind, depth) {
    return cssFontForKind(kind, depth || 0) * activeUnitPerCss;
  }
  function labelWidth(lines, kind, depth) {
    const size = fontSizeForKind(kind, depth);
    let widest = 0;
    lines.forEach(function (line) {
      widest = Math.max(widest, characterUnits(line) * size * 0.52);
    });
    return widest;
  }
  function wrappedForItem(item) {
    const node = item.node;
    return wrapLabel(node.text, node.kind, node.status, node.kind === "goal");
  }
  function computeViewBox(laidOutTree) {
    const box = { minX: -60, maxX: 60, minY: -40, maxY: 40 };
    laidOutTree.nodes.forEach(function (item) {
      const wrapped = wrappedForItem(item);
      const width = labelWidth(wrapped.lines, item.node.kind, item.depth);
      const pointsRight = Math.cos(item.angle) >= 0 || item.depth === 0;
      let labelX = item.x - width / 2;
      if (item.depth !== 0) {
        labelX = pointsRight ? item.x + LABEL_BOX_OFFSET : item.x - LABEL_BOX_OFFSET - width;
      }
      box.minX = Math.min(box.minX, labelX - 8, item.x - 12);
      box.maxX = Math.max(box.maxX, labelX + width + 8, item.x + 12);
      box.minY = Math.min(box.minY, item.y - 28);
      box.maxY = Math.max(box.maxY, item.y + wrapped.lines.length * (fontSizeForKind(item.node.kind, item.depth) * 1.1) + 8);
    });
    return { x: box.minX - 36, y: box.minY - 36, w: box.maxX - box.minX + 72, h: box.maxY - box.minY + 72 };
  }
  function goalEllipse(goalItem) {
    const wrapped = wrappedForItem(goalItem);
    return {
      rx: labelWidth(wrapped.lines, "goal", 0) / 2 + 20,
      ry: wrapped.lines.length * (fontSizeForKind("goal", 0) * 0.58) + 16
    };
  }
  function lineStartPoint(item, positions, ellipse) {
    const parentPosition = positions[String(item.parent.node.id)] || item.parent;
    const childPosition = positions[String(item.node.id)] || item;
    if (item.parent.depth !== 0 || !ellipse) {
      return { x: parentPosition.x, y: parentPosition.y };
    }
    const deltaX = childPosition.x - parentPosition.x;
    const deltaY = childPosition.y - parentPosition.y;
    const length = Math.max(1, Math.hypot(deltaX, deltaY));
    const unitX = deltaX / length;
    const unitY = deltaY / length;
    const denominator = Math.sqrt(Math.pow(ellipse.ry * unitX, 2) + Math.pow(ellipse.rx * unitY, 2));
    const distance = (ellipse.rx * ellipse.ry) / Math.max(1, denominator);
    return { x: parentPosition.x + unitX * distance, y: parentPosition.y + unitY * distance };
  }
  function createMarkContents(item, palette, theme) {
    const kind = item.node.kind;
    const group = createSvgElement("g", {});
    if (kind === "goal") {
      return group;
    }
    if (kind === "point" && item.node.status === "未展开") {
      const circle = createSvgElement("circle", { r: 7, fill: "none", stroke: palette.amber, "stroke-width": 2 });
      circle.setAttribute("class", "map-unexpanded");
      group.appendChild(circle);
    } else if (kind === "point") {
      const attrs = { r: 5, fill: palette.star, class: theme === "paper" ? "" : "map-glow" };
      group.appendChild(createSvgElement("circle", attrs));
    } else if (kind === "decision") {
      group.appendChild(createSvgElement("path", { d: "M0,-7 L6,0 L0,7 L-6,0 Z", fill: palette.star }));
    } else if (kind === "todo") {
      const attrs = { x: -5, y: -5, width: 10, height: 10, fill: "none", stroke: palette.text, "stroke-width": 1.6 };
      group.appendChild(createSvgElement("rect", attrs));
    } else if (kind === "question") {
      const attrs = { r: 6, fill: "none", stroke: palette.parked, "stroke-width": 1.8 };
      group.appendChild(createSvgElement("circle", attrs));
    } else if (kind === "contradiction") {
      const attrs = { d: "M-6,0 L6,0 M0,-6 L0,6", stroke: palette.signal, "stroke-width": 2.4 };
      group.appendChild(createSvgElement("path", attrs));
    } else if (kind === "task") {
      appendTaskMark(group, item, palette, theme);
    } else {
      group.appendChild(createSvgElement("circle", { r: 4, fill: palette.text }));
    }
    return group;
  }
  function appendTaskMark(group, item, palette, theme) {
    const status = item.node.status;
    let fill = palette.amber;
    if (status === "failed") {
      fill = palette.dim;
    } else if (status === "done") {
      fill = palette.star;
    }
    const dot = createSvgElement("circle", { r: status === "running" ? 6 : 4.5, fill: fill });
    if (status === "running" && theme !== "paper") {
      dot.setAttribute("class", "map-pulse");
    }
    group.appendChild(dot);
  }
  function ensureLayers(svgElement) {
    const existingConnectors = svgElement._connectorLayer;
    const existingNodes = svgElement._nodeLayer;
    if (existingConnectors && existingNodes && existingConnectors.parentNode === svgElement && existingNodes.parentNode === svgElement) {
      if (svgElement.firstChild !== existingConnectors) {
        svgElement.insertBefore(existingConnectors, svgElement.firstChild);
      }
      if (existingConnectors.nextSibling !== existingNodes) {
        svgElement.insertBefore(existingNodes, existingConnectors.nextSibling);
      }
      return { connectors: existingConnectors, nodes: existingNodes };
    }
    const connectors = createSvgElement("g", { class: "map-connectors" });
    const nodes = createSvgElement("g", { class: "map-nodes" });
    svgElement.appendChild(connectors);
    svgElement.appendChild(nodes);
    svgElement._connectorLayer = connectors;
    svgElement._nodeLayer = nodes;
    return { connectors: connectors, nodes: nodes };
  }
  function ensureElements(svgElement, laidOutTree, palette, theme) {
    if (!svgElement._els) {
      svgElement._els = {};
    }
    ensureLayers(svgElement);
    const elementsById = svgElement._els;
    const seenIds = {};
    laidOutTree.nodes.forEach(function (item) {
      const id = String(item.node.id);
      seenIds[id] = true;
      let entry = elementsById[id];
      if (!entry) {
        entry = createNodeElements(svgElement);
        elementsById[id] = entry;
      }
      updateHalo(entry, item, theme);
      updateMark(entry, item, palette, theme);
      updateLabel(entry, item, palette, theme);
    });
    removeStaleElements(elementsById, seenIds);
    return elementsById;
  }
  function createNodeElements(svgElement) {
    const layers = ensureLayers(svgElement);
    const entry = {};
    entry.line = createSvgElement("line", {});
    layers.connectors.appendChild(entry.line);
    entry.group = createSvgElement("g", {});
    entry.halo = createSvgElement("ellipse", {});
    entry.group.appendChild(entry.halo);
    entry.title = createSvgElement("title", {});
    entry.group.appendChild(entry.title);
    entry.text = createSvgElement("text", {});
    entry.text.setAttribute("class", "map-label");
    entry.group.appendChild(entry.text);
    entry.markHolder = createSvgElement("g", {});
    entry.group.appendChild(entry.markHolder);
    layers.nodes.appendChild(entry.group);
    return entry;
  }
  function updateHalo(entry, item, theme) {
    if (item.node.kind !== "goal") {
      entry.halo.setAttribute("display", "none");
      return;
    }
    const ellipse = goalEllipse(item);
    entry.halo.removeAttribute("display");
    entry.halo.setAttribute("rx", ellipse.rx + 6);
    entry.halo.setAttribute("ry", ellipse.ry + 6);
    entry.halo.setAttribute("fill", theme === "paper" ? "#f6f1e7" : "#000000");
    entry.halo.setAttribute("opacity", theme === "paper" ? "0.96" : "0.92");
    entry.halo.setAttribute("class", "map-goal-halo");
  }
  function updateMark(entry, item, palette, theme) {
    entry.markHolder.setAttribute("transform", "scale(" + activeMarkScale + ")");
    const signature = item.node.kind + "|" + item.node.status + "|" + theme + "|" + activeMarkScale;
    if (entry.markSignature === signature) {
      return;
    }
    entry.markSignature = signature;
    while (entry.markHolder.firstChild) {
      entry.markHolder.removeChild(entry.markHolder.firstChild);
    }
    const mark = createMarkContents(item, palette, theme);
    while (mark.firstChild) {
      entry.markHolder.appendChild(mark.firstChild);
    }
    entry.markHolder.setAttribute("transform", "scale(" + activeMarkScale + ")");
  }
  function updateLabel(entry, item, palette, theme) {
    const wrapped = wrappedForItem(item);
    entry.text.style.strokeWidth = String(6 * activeUnitPerCss);
    const signature = wrapped.lines.join("\n") + "|" + item.node.kind + "|" + theme + "|" + fontSizeForKind(item.node.kind, item.depth);
    if (entry.labelSignature === signature) {
      return;
    }
    entry.labelSignature = signature;
    while (entry.text.firstChild) {
      entry.text.removeChild(entry.text.firstChild);
    }
    entry.title.textContent = wrapped.full;
    const pointsRight = item.depth === 0 || Math.cos(item.angle) >= 0;
    const textX = item.depth === 0 ? 0 : (pointsRight ? LABEL_OFFSET * activeMarkScale : -LABEL_OFFSET * activeMarkScale);
    entry.text.setAttribute("x", textX);
    entry.text.setAttribute("y", item.depth === 0 ? fontSizeForKind("goal", 0) * 0.32 : fontSizeForKind(item.node.kind, item.depth) * 0.32);
    entry.text.setAttribute("text-anchor", anchorFor(item.depth, pointsRight));
    entry.text.setAttribute("fill", fillForKind(item.node.kind, palette, theme));
    entry.text.setAttribute("font-size", fontSizeForKind(item.node.kind, item.depth));
    entry.text.setAttribute("font-weight", weightForKind(item.node.kind, theme));
    const glowClass = theme !== "paper" && item.node.kind === "goal" ? " map-glow" : "";
    entry.text.setAttribute("class", "map-label" + glowClass);
    appendLabelLines(entry.text, wrapped.lines, textX, item.node.kind, item.depth);
  }
  function anchorFor(depth, pointsRight) {
    if (depth === 0) {
      return "middle";
    }
    return pointsRight ? "start" : "end";
  }
  function fillForKind(kind, palette, theme) {
    if (kind === "question") {
      return palette.parked;
    }
    if (kind === "contradiction") {
      return theme === "paper" ? palette.text : palette.amber;
    }
    return palette.text;
  }
  function weightForKind(kind, theme) {
    if (kind === "goal") {
      return 300;
    }
    if (kind === "decision") {
      return 600;
    }
    return theme === "paper" ? 400 : 300;
  }
  function appendLabelLines(textElement, lines, textX, kind, depth) {
    lines.forEach(function (lineText, index) {
      const lineHeight = fontSizeForKind(kind, depth) * 1.1;
      const span = createSvgElement("tspan", { x: textX, dy: index === 0 ? 0 : lineHeight });
      span.textContent = lineText;
      textElement.appendChild(span);
    });
  }
  function removeStaleElements(elementsById, seenIds) {
    Object.keys(elementsById).forEach(function (id) {
      if (seenIds[id]) {
        return;
      }
      const entry = elementsById[id];
      if (entry.line.parentNode) {
        entry.line.parentNode.removeChild(entry.line);
      }
      if (entry.group.parentNode) {
        entry.group.parentNode.removeChild(entry.group);
      }
      delete elementsById[id];
    });
  }
  function paintFrame(context, progress, positions, viewBox, isFinal) {
    const svgElement = context.svgElement;
    if (Number.isFinite(viewBox.w) && Number.isFinite(viewBox.h) && viewBox.w > 0 && viewBox.h > 0) {
      const viewBoxText = viewBox.x + " " + viewBox.y + " " + viewBox.w + " " + viewBox.h;
      svgElement.setAttribute("viewBox", viewBoxText);
    }
    context.laidOutTree.nodes.forEach(function (item) {
      paintConnector(context, item, progress, positions, isFinal);
    });
    context.laidOutTree.nodes.forEach(function (item) {
      const entry = context.elementsById[String(item.node.id)];
      if (!entry) {
        return;
      }
      const position = positions[String(item.node.id)] || item;
      const isNew = !context.seenBefore[String(item.node.id)];
      const dimmed = context.theme !== "paper" && activeDimIds[String(item.node.id)];
      const baseOpacity = dimmed ? 0.55 : 1;
      entry.group.setAttribute("transform", "translate(" + position.x + "," + position.y + ")");
      entry.group.setAttribute("opacity", context.animate && isNew ? String((isFinal ? 1 : progress) * baseOpacity) : String(baseOpacity));
      const isNewest = context.theme !== "paper" && String(item.node.id) === context.newestId && Date.now() < context.newestUntil;
      entry.group.setAttribute("class", isNewest ? "map-new-glow" : "");
    });
  }
  function paintConnector(context, item, progress, positions, isFinal) {
    if (!item.parent) {
      return;
    }
    const entry = context.elementsById[String(item.node.id)];
    if (!entry) {
      return;
    }
    const parentPosition = positions[String(item.parent.node.id)] || item.parent;
    const childPosition = positions[String(item.node.id)] || item;
    const start = lineStartPoint(item, positions, context.ellipse);
    const isContradiction = item.node.kind === "contradiction";
    const isNew = !context.seenBefore[String(item.node.id)];
    entry.line.setAttribute("x1", start.x);
    entry.line.setAttribute("y1", start.y);
    entry.line.setAttribute("x2", childPosition.x);
    entry.line.setAttribute("y2", childPosition.y);
    entry.line.setAttribute("stroke", isContradiction ? context.palette.signal : context.palette.line);
    const minimumCss = context.theme === "paper" ? 1.2 : 1.5;
    const lineCss = isContradiction ? 1 : minimumCss;
    entry.line.setAttribute("stroke-width", lineCss * activeUnitPerCss);
    paintConnectorDash(context, entry, start, childPosition, progress, isFinal, isNew, isContradiction);
  }
  function paintConnectorDash(context, entry, start, end, progress, isFinal, isNew, isContradiction) {
    if (context.animate && isNew && !isFinal) {
      const length = Math.max(1, Math.hypot(end.x - start.x, end.y - start.y));
      entry.line.setAttribute("stroke-dasharray", String(length));
      entry.line.setAttribute("stroke-dashoffset", String(length * (1 - progress)));
      return;
    }
    entry.line.setAttribute("stroke-dasharray", isContradiction ? "4 4" : "none");
    entry.line.removeAttribute("stroke-dashoffset");
  }
  function finalPositionsFor(laidOutTree) {
    const positions = {};
    laidOutTree.nodes.forEach(function (item) {
      positions[String(item.node.id)] = { x: item.x, y: item.y };
    });
    return positions;
  }
  function startPositionsFor(laidOutTree, previousPositions) {
    const positions = {};
    laidOutTree.nodes.forEach(function (item) {
      const id = String(item.node.id);
      const previous = previousPositions[id];
      if (previous) {
        positions[id] = { x: previous.x, y: previous.y };
        return;
      }
      const parentId = item.parent ? String(item.parent.node.id) : "";
      if (item.parent && previousPositions[parentId]) {
        const parentPrevious = previousPositions[parentId];
        positions[id] = { x: parentPrevious.x, y: parentPrevious.y };
        return;
      }
      positions[id] = { x: item.x, y: item.y };
    });
    return positions;
  }
  function finishRender(context, finalPositions) {
    const seenIds = {};
    context.laidOutTree.nodes.forEach(function (item) {
      seenIds[String(item.node.id)] = true;
    });
    context.svgElement._blackoutSeen = seenIds;
    paintFrame(context, 1, finalPositions, context.viewBox, true);
    context.svgElement._blackoutSignature = context.signature;
    context.svgElement._blackoutPositions = finalPositions;
    context.svgElement._blackoutBox = context.viewBox;
  }
  function animateRender(context, finalPositions, startPositions) {
    const startBox = context.previousBox;
    const endBox = context.viewBox;
    const startedAt = performance.now();
    function frame(now) {
      const rawProgress = Math.min(1, Math.max(0, (now - startedAt) / 600));
      const easedProgress = 1 - Math.pow(1 - rawProgress, 3);
      const positions = interpolatePositions(startPositions, finalPositions, easedProgress);
      const viewBox = interpolateViewBox(startBox, endBox, easedProgress);
      if (rawProgress < 1) {
        paintFrame(context, easedProgress, positions, viewBox, false);
        requestAnimationFrame(frame);
      } else {
        finishRender(context, finalPositions);
      }
    }
    requestAnimationFrame(frame);
  }
  function interpolatePositions(startPositions, finalPositions, progress) {
    const positions = {};
    Object.keys(finalPositions).forEach(function (id) {
      const start = startPositions[id] || finalPositions[id];
      const end = finalPositions[id];
      positions[id] = {
        x: start.x + (end.x - start.x) * progress,
        y: start.y + (end.y - start.y) * progress
      };
    });
    return positions;
  }
  function interpolateViewBox(startBox, endBox, progress) {
    return {
      x: startBox.x + (endBox.x - startBox.x) * progress,
      y: startBox.y + (endBox.y - startBox.y) * progress,
      w: startBox.w + (endBox.w - startBox.w) * progress,
      h: startBox.h + (endBox.h - startBox.h) * progress
    };
  }
  function expandViewBoxToClientWidth(svgElement, viewBox) {
    const clientWidth = svgElement.clientWidth || 1280;
    if (viewBox.w >= clientWidth / 1.2) {
      return viewBox;
    }
    const extra = clientWidth / 1.2 - viewBox.w;
    return { x: viewBox.x - extra / 2, y: viewBox.y, w: viewBox.w + extra, h: viewBox.h };
  }
  function registerForResize(svgElement, tree, options) {
    let found = null;
    renderRegistry.forEach(function (entry) {
      if (entry.svgElement === svgElement) { found = entry; }
    });
    if (found) {
      found.tree = tree;
      found.options = options;
      return;
    }
    renderRegistry.push({ svgElement: svgElement, tree: tree, options: options });
  }
  function onResize() {
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(function () {
      renderRegistry.slice().forEach(function (entry) {
        if (!entry.svgElement.isConnected) { return; }
        entry.svgElement._blackoutSignature = "";
        render(entry.svgElement, entry.tree, entry.options);
      });
    }, 120);
  }
  window.addEventListener("resize", onResize);
  function render(svgElement, tree, options) {
    if (!svgElement || !tree) {
      return;
    }
    const renderOptions = options || {};
    const theme = renderOptions.theme === "paper" ? "paper" : "night";
    registerForResize(svgElement, tree, renderOptions);
    const shouldAnimate = Boolean(renderOptions.animate) && theme !== "paper" && !prefersReducedMotion() && !isDocumentHidden();
    const signature = JSON.stringify(tree) + "|" + theme + "|" + (svgElement.clientWidth || 0) + "x" + (svgElement.clientHeight || 0);
    if (svgElement._blackoutSignature === signature) {
      return;
    }
    svgElement.setAttribute("class", theme === "paper" ? "map-paper" : "map-night");
    svgElement.setAttribute("preserveAspectRatio", "xMidYMid meet");
    prepareActiveDisplay(svgElement, tree, theme);
    const context = buildRenderContext(svgElement, tree, theme, shouldAnimate, signature);
    context.newestId = svgElement._blackoutNewestId || "";
    context.newestUntil = svgElement._blackoutNewestUntil || 0;
    const finalPositions = finalPositionsFor(context.laidOutTree);
    const startPositions = startPositionsFor(context.laidOutTree, context.previousPositions);
    const hasPrevious = Object.keys(context.previousPositions).length > 0;
    if (!shouldAnimate || !hasPrevious) {
      finishRender(context, finalPositions);
      return;
    }
    animateRender(context, finalPositions, startPositions);
  }
  function buildRenderContext(svgElement, tree, theme, shouldAnimate, signature) {
    activeTheme = theme;
    activeUnitPerCss = 1;
    activeMarkScale = 1;
    let laidOutTree = layoutTree(tree);
    let viewBox = expandViewBoxToClientWidth(svgElement, computeViewBox(laidOutTree));
    for (let pass = 0; pass < 3; pass += 1) {
      const renderedWidth = svgElement.clientWidth || 1280;
      const scale = renderedWidth / Math.max(1, viewBox.w);
      activeUnitPerCss = scale > 0 && Number.isFinite(scale) ? 1 / scale : 1;
      activeMarkScale = fontSizeForKind("point", 2) / 19;
      laidOutTree = layoutTree(tree);
      viewBox = expandViewBoxToClientWidth(svgElement, computeViewBox(laidOutTree));
    }
    const palette = paletteForTheme(theme);
    const goalItem = laidOutTree.nodes[0];
    return {
      svgElement: svgElement,
      laidOutTree: laidOutTree,
      palette: palette,
      theme: theme,
      animate: shouldAnimate,
      signature: signature,
      viewBox: viewBox,
      previousBox: svgElement._blackoutBox || viewBox,
      previousPositions: svgElement._blackoutPositions || {},
      seenBefore: svgElement._blackoutSeen || {},
      ellipse: goalItem ? goalEllipse(goalItem) : null,
      elementsById: ensureElements(svgElement, laidOutTree, palette, theme),
      newestId: "",
      newestUntil: 0
    };
  }
  function renderOutline(container, tree) {
    if (!container || !tree) {
      return;
    }
    container.replaceChildren();
    container.classList.add("map-outline");
    const children = tree.children || [];
    if (!children.length) {
      return;
    }
    const rootList = document.createElement("ul");
    children.forEach(function (child) {
      rootList.appendChild(buildOutlineItem(child));
    });
    container.appendChild(rootList);
  }
  function buildOutlineItem(node) {
    const listItem = document.createElement("li");
    const mark = document.createElement("span");
    const kindClass = "kind-" + String(node.kind || "");
    const statusClass = "status-" + String(node.status || "");
    mark.className = "map-outline-mark " + kindClass + " " + statusClass;
    mark.setAttribute("aria-hidden", "true");
    listItem.appendChild(mark);
    const text = document.createElement("span");
    text.textContent = String(node.text || "");
    listItem.appendChild(text);
    const children = node.children || [];
    if (children.length) {
      const childList = document.createElement("ul");
      children.forEach(function (child) {
        childList.appendChild(buildOutlineItem(child));
      });
      listItem.appendChild(childList);
    }
    return listItem;
  }
  return { render: render, renderOutline: renderOutline };
})();
