"""Connectivity graph derived purely from geometry.

Nodes are entity ids ("E12"), junctions ("J3", tees or pipe-to-pipe joints) and free pipe ends
("F:L4:end"). Every line becomes a chain of nodes ordered along the pipe:

    start-node -> inline valve / tee junction ... -> end-node

Line point order is taken as flow direction, which gives us directed upstream/downstream edges for
process lines. Nothing here is stored: topology is rebuilt from the document whenever it is needed,
so edits can never leave it stale.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from . import geometry as g
from .document import entity_bbox, snap_tolerance
from .symbols import category

INLINE_CATEGORIES = {"valve", "instrument"}


@dataclass
class Topology:
    tol: float
    boxes: dict[str, list[float]]
    ends: dict[str, dict[str, str]] = field(default_factory=dict)          # line -> {"start": node, "end": node}
    chain: dict[str, list[str]] = field(default_factory=dict)              # line -> ordered nodes
    kind: dict[str, str] = field(default_factory=dict)                     # line -> process | signal
    adj: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    padj: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))   # process only, undirected
    succ: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))   # process only, downstream
    pred: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    edge_line: dict[tuple[str, str], str] = field(default_factory=dict)
    node_lines: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    junction_pos: dict[str, list[float]] = field(default_factory=dict)
    dangling: list[tuple[str, str, list[float]]] = field(default_factory=list)   # (line, "start"|"end", point)
    attachments: dict[str, list[tuple[str, str]]] = field(default_factory=lambda: defaultdict(list))
    inline: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))

    # ---- queries -----------------------------------------------------------------------------------

    def lines_of(self, ent_id: str, kind: str | None = None) -> set[str]:
        return {ln for ln in self.node_lines.get(ent_id, set()) if kind is None or self.kind[ln] == kind}

    def is_connected(self, ent_id: str, kind: str | None = None) -> bool:
        return bool(self.lines_of(ent_id, kind))

    def neighbours(self, ent_id: str, kind: str | None = None, max_hops: int = 50) -> set[str]:
        """Entities reachable over pipes without passing through another entity."""
        adj = self.padj if kind == "process" else self.adj
        seen, out, stack = {ent_id}, set(), [(n, 1) for n in adj.get(ent_id, ())]
        while stack:
            node, hops = stack.pop()
            if node in seen or hops > max_hops:
                continue
            seen.add(node)
            if node.startswith("E"):
                out.add(node)
                continue
            stack.extend((n, hops + 1) for n in adj.get(node, ()))
        return out

    def branches(self, ent_id: str, stop_types: set[str], types: dict[str, str]) -> list[dict]:
        """Walk each process branch leaving an entity until equipment, a junction or a free end.

        Returns [{"nodes": [...], "first_line": line_id, "outgoing": bool, "end": node}].
        """
        out = []
        for first in sorted(self.padj.get(ent_id, ())):
            nodes, prev, cur = [], ent_id, first
            while True:
                nodes.append(cur)
                if cur.startswith(("J", "F")) or types.get(cur) in stop_types:
                    break
                nxt = [n for n in self.padj.get(cur, ()) if n != prev and n not in nodes and n != ent_id]
                if len(nxt) != 1 or len(nodes) > 30:
                    break
                prev, cur = cur, nxt[0]
            out.append({
                "nodes": nodes,
                "first_line": self.edge_line.get((ent_id, first)),
                "outgoing": first in self.succ.get(ent_id, ()),
                "end": nodes[-1],
            })
        return out


def _closest_entity(p, boxes: dict[str, list[float]], tol: float, exclude: set[str] = frozenset()) -> str | None:
    best, best_key = None, None
    for eid, box in boxes.items():
        if eid in exclude or not g.bbox_contains(box, p, tol):
            continue
        dx = max(box[0] - p[0], 0, p[0] - box[2])
        dy = max(box[1] - p[1], 0, p[1] - box[3])
        area = (box[2] - box[0]) * (box[3] - box[1])
        key = (round((dx * dx + dy * dy) ** 0.5, 6), area)
        if best_key is None or key < best_key:
            best, best_key = eid, key
    return best


def build(doc: dict) -> Topology:
    tol = snap_tolerance(doc)
    boxes = {e["id"]: entity_bbox(doc, e) for e in doc["entities"] if e["type"] != "title_block"}
    topo = Topology(tol=tol, boxes=boxes)
    lines = [ln for ln in doc["lines"] if len(ln["pts"]) >= 2]

    # 1. pipe ends that land on a symbol
    loose: list[tuple[str, str, list[float]]] = []
    for ln in lines:
        topo.kind[ln["id"]] = ln.get("kind", "process")
        topo.ends[ln["id"]] = {}
        for end, p in (("start", ln["pts"][0]), ("end", ln["pts"][-1])):
            eid = _closest_entity(p, boxes, tol)
            if eid:
                topo.ends[ln["id"]][end] = eid
                topo.attachments[eid].append((ln["id"], end))
            else:
                loose.append((ln["id"], end, p))

    # 2. pipe ends meeting other pipe ends (same kind) -> shared junction
    jcount = 0
    cluster_of: dict[tuple[str, str], str] = {}
    for i, (lid, end, p) in enumerate(loose):
        if (lid, end) in cluster_of:
            continue
        members = [(lid, end, p)]
        for lid2, end2, p2 in loose[i + 1:]:
            if (lid2, end2) not in cluster_of and topo.kind[lid2] == topo.kind[lid] and g.dist(p, p2) <= tol and lid2 != lid:
                members.append((lid2, end2, p2))
        if len(members) > 1:
            jcount += 1
            jid = f"J{jcount}"
            topo.junction_pos[jid] = list(p)
            for m in members:
                cluster_of[(m[0], m[1])] = jid

    # 3. pipe ends landing on the middle of another pipe -> tee junction
    tees: dict[str, list[tuple[float, str]]] = defaultdict(list)   # host line -> [(distance along, node)]
    for lid, end, p in loose:
        node = cluster_of.get((lid, end))
        for host in lines:
            if host["id"] == lid or topo.kind[host["id"]] != topo.kind[lid]:
                continue
            d, seg, t, q = g.point_polyline(p, host["pts"])
            if d > tol or g.dist(q, host["pts"][0]) <= tol or g.dist(q, host["pts"][-1]) <= tol:
                continue
            if node is None:
                jcount += 1
                node = f"J{jcount}"
                topo.junction_pos[node] = q
                cluster_of[(lid, end)] = node
            along = g.polyline_length(host["pts"][: seg + 1]) + g.dist(host["pts"][seg], q)
            if node not in [n for _, n in tees[host["id"]]]:
                tees[host["id"]].append((along, node))
            break

    for lid, end, p in loose:
        node = cluster_of.get((lid, end))
        if node is None:
            node = f"F:{lid}:{end}"
            if topo.kind[lid] == "process":
                topo.dangling.append((lid, end, list(p)))
        topo.ends[lid][end] = node

    # 4. symbols a pipe runs straight through (valves / instruments drawn over an unbroken line)
    inline_items: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for ln in lines:
        attached = {topo.ends[ln["id"]]["start"], topo.ends[ln["id"]]["end"]}
        for e in doc["entities"]:
            if e["id"] in attached or category(e["type"]) not in INLINE_CATEGORIES:
                continue
            box = boxes[e["id"]]
            w, h = g.bbox_size(box)
            inner = [box[0] + 0.2 * w, box[1] + 0.2 * h, box[2] - 0.2 * w, box[3] - 0.2 * h]
            along = 0.0
            for i in range(len(ln["pts"]) - 1):
                a, b = ln["pts"][i], ln["pts"][i + 1]
                clip = g.seg_bbox_clip(a, b, inner)
                if clip:
                    inline_items[ln["id"]].append((along + g.dist(a, b) * (clip[0] + clip[1]) / 2, e["id"]))
                    topo.inline[e["id"]].append(ln["id"])
                    break
                along += g.dist(a, b)

    # 5. chains and edges
    for ln in lines:
        lid = ln["id"]
        mids = sorted(tees.get(lid, []) + inline_items.get(lid, []))
        chain = [topo.ends[lid]["start"]] + [n for _, n in mids] + [topo.ends[lid]["end"]]
        topo.chain[lid] = chain
        for node in chain:
            topo.node_lines[node].add(lid)
        for u, v in zip(chain, chain[1:]):
            if u == v:
                continue
            topo.adj[u].add(v)
            topo.adj[v].add(u)
            topo.edge_line.setdefault((u, v), lid)
            topo.edge_line.setdefault((v, u), lid)
            if topo.kind[lid] == "process":
                topo.padj[u].add(v)
                topo.padj[v].add(u)
                topo.succ[u].add(v)
                topo.pred[v].add(u)
    return topo


def summary(topo: Topology) -> dict:
    """Compact, JSON-friendly view for the frontend (used to preview drags)."""
    return {
        "tol": topo.tol,
        "attachments": {k: [[ln, end] for ln, end in v] for k, v in topo.attachments.items()},
        "dangling": [[ln, end, p] for ln, end, p in topo.dangling],
    }
