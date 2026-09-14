"""Turns the flat list of FileChange objects into a nested tree for the UI.

Directory nodes get a "status" too, derived from their children, so the
tree can show e.g. a folder icon tinted to indicate it contains changes.
"""

from __future__ import annotations

from app.models.comparison import ChangeStatus, FileChange

_STATUS_PRIORITY = {
    ChangeStatus.MODIFIED: 4,
    ChangeStatus.RENAMED: 4,
    ChangeStatus.ADDED: 3,
    ChangeStatus.DELETED: 3,
    ChangeStatus.UNCHANGED: 1,
}


def build_tree(changes: list[FileChange]) -> dict:
    root: dict = {"name": "", "path": "", "type": "dir", "children": {}, "status": None}

    for change in changes:
        parts = change.rel_path.split("/")
        node = root
        for i, part in enumerate(parts):
            is_leaf = i == len(parts) - 1
            children = node["children"]
            if part not in children:
                children[part] = {
                    "name": part,
                    "path": "/".join(parts[: i + 1]),
                    "type": "file" if is_leaf else "dir",
                    "children": {},
                    "status": None,
                }
            node = children[part]
            if is_leaf:
                node["status"] = change.status.value
                node["is_binary"] = change.is_binary
                node["left_path"] = change.left_path
                node["right_path"] = change.right_path
                node["size_left"] = change.size_left
                node["size_right"] = change.size_right
                node["similarity"] = change.similarity
            else:
                # Propagate the "most significant" status upward so parent
                # directories visually indicate they contain changes.
                current = node.get("_priority", 0)
                incoming = _STATUS_PRIORITY.get(change.status, 0)
                if incoming >= current:
                    node["_priority"] = incoming
                    node["status"] = "modified" if incoming >= 3 else node["status"]

    def finalize(node: dict) -> dict:
        node["children"] = sorted(
            (finalize(c) for c in node["children"].values()),
            key=lambda n: (n["type"] != "dir", n["name"].lower()),
        )
        node.pop("_priority", None)
        return node

    finalized = finalize(root)
    return finalized
