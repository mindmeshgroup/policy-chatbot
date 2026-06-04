from qdrant_client import QdrantClient
from qdrant_client.models import (
    CreateAlias,
    CreateAliasOperation,
    DeleteAlias,
    DeleteAliasOperation,
)

from retrieval.config import (
    COLLECTION_ALIAS,
    QDRANT_API_KEY,
    QDRANT_URL,
)

def promote_candidate_collection(collection_name: str) -> None:
    """
    Routes the live collection alias to a tested candidate collection.
    """
    client = QdrantClient(
        url=QDRANT_URL,
        api_key=QDRANT_API_KEY,
    )

    if not client.collection_exists(collection_name):
        raise RuntimeError(f"Cannot promote '{collection_name}' because it does not exist.")

    point_count = client.count(collection_name=collection_name, exact=True).count
    if point_count == 0:
        raise RuntimeError(f"Cannot promote '{collection_name}' because it contains no vectors.")

    aliases = client.get_aliases().aliases
    alias_names = {alias.alias_name for alias in aliases}

    if COLLECTION_ALIAS not in alias_names and client.collection_exists(COLLECTION_ALIAS):
        raise RuntimeError(
            f"Cannot use '{COLLECTION_ALIAS}' as an alias because a physical "
            "collection already exists with that name."
        )

    operations = []

    if COLLECTION_ALIAS in alias_names:
        operations.append(
            DeleteAliasOperation(delete_alias=DeleteAlias(alias_name=COLLECTION_ALIAS))
        )

    operations.append(
        CreateAliasOperation(
            create_alias=CreateAlias(collection_name=collection_name, alias_name=COLLECTION_ALIAS)
        )
    )

    client.update_collection_aliases(change_aliases_operations=operations)
    print(f"[*] SUCCESS: Live alias '{COLLECTION_ALIAS}' now points to '{collection_name}'.")