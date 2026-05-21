import uuid

from app.models.org_structure import OrgStructure
from app.schemas.org_schema import OrgResponse, OrgTreeResponse


def build_org_tree(org_rows: list[OrgStructure]) -> list[OrgTreeResponse]:
    node_map: dict[uuid.UUID, OrgTreeResponse] = {}
    root_nodes: list[OrgTreeResponse] = []

    for row in org_rows:
        base_payload = OrgResponse.model_validate(row).model_dump()
        node_map[row.id] = OrgTreeResponse(**base_payload, children=[])

    for row in org_rows:
        node = node_map[row.id]
        parent_key = row.parent_id
        if parent_key and parent_key in node_map:
            node_map[parent_key].children.append(node)
        else:
            root_nodes.append(node)

    return root_nodes
