import os
import dotenv
dotenv.load_dotenv("../.env")
from langchain_community.graphs import Neo4jGraph

neo4j_graph = Neo4jGraph("neo4j://127.0.0.1", "neo4j", "12345678", enhanced_schema=True)
print("structured_schema keys:", neo4j_graph.structured_schema.keys())
print("relationships:", neo4j_graph.structured_schema.get("relationships"))