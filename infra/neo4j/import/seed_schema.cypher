// ============================================================================
// DCOps Copilot — Neo4j schema seed
// ============================================================================
// Idempotent constraints and indexes for the asset + dependency graph.
// Run via cypher-shell or `make seed`. Actual data load is done by
// scripts/seed_graph.py (so we can use Python data generators).
//
// Ships: Week 1.
// See ARCHITECTURE.md § Knowledge graph schema.
// ============================================================================

// --- Uniqueness constraints (also create indexes) ---------------------------
CREATE CONSTRAINT site_id_unique     IF NOT EXISTS FOR (s:Site)     REQUIRE s.id IS UNIQUE;
CREATE CONSTRAINT hall_id_unique     IF NOT EXISTS FOR (h:Hall)     REQUIRE h.id IS UNIQUE;
CREATE CONSTRAINT rack_id_unique     IF NOT EXISTS FOR (r:Rack)     REQUIRE r.id IS UNIQUE;
CREATE CONSTRAINT device_id_unique   IF NOT EXISTS FOR (d:Device)   REQUIRE d.id IS UNIQUE;
CREATE CONSTRAINT workload_id_unique IF NOT EXISTS FOR (w:Workload) REQUIRE w.id IS UNIQUE;
CREATE CONSTRAINT incident_id_unique IF NOT EXISTS FOR (i:Incident) REQUIRE i.id IS UNIQUE;
CREATE CONSTRAINT policy_id_unique   IF NOT EXISTS FOR (p:Policy)   REQUIRE p.id IS UNIQUE;

// --- Performance indexes -----------------------------------------------------
CREATE INDEX device_type_idx     IF NOT EXISTS FOR (d:Device)   ON (d.type);
CREATE INDEX device_vendor_idx   IF NOT EXISTS FOR (d:Device)   ON (d.vendor);
CREATE INDEX incident_opened_idx IF NOT EXISTS FOR (i:Incident) ON (i.opened_at);
CREATE INDEX rack_position_idx   IF NOT EXISTS FOR (r:Rack)     ON (r.position);

RETURN 'schema seeded' AS status;
