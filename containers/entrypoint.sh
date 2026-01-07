#!/bin/bash
set -e

DATA_DIR="/home/axiom/data"
LANCEDB_DIR="$DATA_DIR/lancedb"
INITIALIZED_FLAG="$DATA_DIR/.initialized"

# Ensure data directory exists
mkdir -p "$DATA_DIR"

# Wait for Neo4j to be ready
echo "Waiting for Neo4j..."
until python -c "from neo4j import GraphDatabase; d=GraphDatabase.driver('$AXIOM_NEO4J_URI', auth=('$AXIOM_NEO4J_USER','$AXIOM_NEO4J_PASSWORD')); d.verify_connectivity(); d.close()" 2>/dev/null; do
    sleep 2
done
echo "Neo4j ready!"

# First-run initialization
if [ ! -f "$INITIALIZED_FLAG" ]; then
    echo "First startup - initializing axiom database..."

    # Download embedding model
    echo "Downloading embedding model..."
    python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

    # Run ingestion from TOML files into both LanceDB and Neo4j
    echo "Ingesting axioms from TOML files..."
    cd /home/axiom/app
    python -m scripts.ingest --lancedb-path "$LANCEDB_DIR"

    touch "$INITIALIZED_FLAG"
    echo "Initialization complete!"
fi

# Keep container running
echo "Axiom server ready"
exec tail -f /dev/null
