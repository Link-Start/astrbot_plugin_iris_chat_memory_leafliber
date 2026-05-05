import kuzu
import tempfile
import os

tmpdir = tempfile.mkdtemp()
db = kuzu.Database(os.path.join(tmpdir, "test"))
conn = kuzu.Connection(db)
conn.execute(
    "CREATE NODE TABLE Entity(id STRING, label STRING, name STRING, content STRING, group_id STRING, confidence DOUBLE, access_count INT64, last_access_time STRING, source_memory_ids STRING, weight DOUBLE, properties STRING, PRIMARY KEY(id))"
)
conn.execute(
    "CREATE REL TABLE Related(FROM Entity TO Entity, relation_type STRING, weight DOUBLE, confidence DOUBLE, source_memory_ids STRING, properties STRING)"
)
conn.execute(
    "CREATE (n:Entity {id: 'test1', label: 'Person', name: 'Alice', content: 'test', group_id: '', confidence: 0.5, access_count: 0, last_access_time: '', source_memory_ids: '', weight: 0.5, properties: '{}'})"
)
try:
    r = conn.execute(
        "MATCH (e:Entity) WHERE e.id IN $node_ids DELETE e", {"node_ids": ["test1"]}
    )
    print("OK, param deleted")
except Exception as ex:
    print(f"Error: {ex}")
